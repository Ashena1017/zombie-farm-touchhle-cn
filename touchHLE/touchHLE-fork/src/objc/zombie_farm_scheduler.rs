/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Serialize legacy Zombie Farm's guest Cocos manager operations.
//!
//! Cocos publishes a selector hash entry before initializing its timer array.
//! The game's invasion loader mutates the scheduler on a background guest
//! thread while the main thread runs tick:, which can observe that entry.
//! CCActionManager similarly publishes a target before its action array exists.
//! Protect both managers' entire guest methods with one shared recursive gate,
//! including tick:'s cached IMP callbacks. Those callbacks can enter the action
//! manager, whose actions may schedule or unschedule again. Independent locks
//! would permit opposite lock ordering. Never use a host std::sync::Mutex.
//! A direct cached call into a manager method does not go through message
//! dispatch and is not intercepted. Do not replace raw IMPs with objc_msgSend:
//! that would change the caller's selected implementation and _cmd semantics.
//!
//! This protects manager collections; it does not repair stale targets or
//! corrupted particle objects. A callback that synchronously waits for another
//! thread needing this same gate can still create a cross-thread lock cycle.

use super::{Class, ClassHostObject, ObjC};
use crate::abi::GuestFunction;
use crate::environment::MutexType;
use crate::Environment;

fn is_legacy_zfr_bundle(bundle_id: &str) -> bool {
    matches!(
        bundle_id,
        "com.playforge.ZombieFarm.ZFR" | "com.playforge.ZFR.LZ54D2GT3D"
    )
}

fn applies_to_bundle(bundle_id: &str, version: &str) -> bool {
    is_legacy_zfr_bundle(bundle_id) && version == "1.0"
}

/// Walk actual class metadata, including metaclasses and inherited methods.
/// Bound the walk so invalid/cyclic metadata never makes dispatch loop forever.
fn has_cocos_manager_ancestor<'a, C: Copy + Eq>(
    mut class: C,
    nil: C,
    mut class_info: impl FnMut(C) -> Option<(&'a str, C)>,
) -> bool {
    for _ in 0..256 {
        if class == nil {
            return false;
        }
        let Some((name, superclass)) = class_info(class) else {
            return false;
        };
        if matches!(name, "CCScheduler" | "CCActionManager") {
            return true;
        }
        class = superclass;
    }
    false
}

fn is_cocos_manager_class(objc: &ObjC, class: Class) -> bool {
    has_cocos_manager_ancestor(class, super::nil, |class| {
        let info = objc
            .get_host_object(class)?
            .as_any()
            .downcast_ref::<ClassHostObject>()?;
        Some((info.name.as_str(), info.superclass))
    })
}

/// Restrict message-dispatch serialization to the two supported Cocos managers.
pub(crate) fn needs_serialization(env: &Environment, class: Class) -> bool {
    let bundle_id = env.bundle.bundle_identifier();
    // Other apps and the app picker need not have CFBundleVersion. Do not read
    // it until the exact supported bundle identifier has matched.
    is_legacy_zfr_bundle(bundle_id)
        && applies_to_bundle(bundle_id, env.bundle.bundle_version())
        && is_cocos_manager_class(&env.objc, class)
}

/// No new guest stack frame or argument rewriting: preserve objc_msgSend's
/// pass-through ABI, especially scheduleSelector:'s arguments on the stack.
pub(super) fn call_guest_imp(env: &mut Environment, class: Class, imp: GuestFunction) {
    if !needs_serialization(env, class) {
        imp.call_without_pushing_stack_frame(env);
        return;
    }

    let mutex = if let Some(mutex) = env.objc.zombie_farm_scheduler_mutex {
        mutex
    } else {
        let mutex = env
            .mutex_state
            .init_mutex(MutexType::PTHREAD_MUTEX_RECURSIVE);
        env.objc.zombie_farm_scheduler_mutex = Some(mutex);
        log!("ZombieFarm workaround: serializing Cocos scheduler/action-manager guest methods");
        mutex
    };

    // lock_mutex suspends only the contending guest thread. run_call resumes
    // this same thread before returning; nested manager calls recurse safely.
    env.lock_mutex(mutex).unwrap();
    imp.call_without_pushing_stack_frame(env);
    env.unlock_mutex(mutex).unwrap();
}

#[cfg(test)]
mod tests {
    use super::{applies_to_bundle, has_cocos_manager_ancestor};

    #[test]
    fn only_the_two_supported_legacy_bundles_are_affected() {
        for id in [
            "com.playforge.ZombieFarm.ZFR",
            "com.playforge.ZFR.LZ54D2GT3D",
        ] {
            assert!(applies_to_bundle(id, "1.0"));
            assert!(!applies_to_bundle(id, "1.1"));
            assert!(!applies_to_bundle(id, "2.0"));
        }
        for id in [
            "com.playforge.ZombieFarm",
            "com.playforge.ZombieFarm.ZFR.extra",
            "com.playforge.ZombieFarm2",
            "other.CCScheduler",
        ] {
            assert!(!applies_to_bundle(id, "1.0"));
        }
    }

    #[test]
    fn both_managers_and_their_subclasses_and_metaclasses_share_the_gate() {
        // The overridden method's implementation class may be a subclass.
        // Decide from ancestry rather than its name or a list of selectors.
        let classes = [
            ("", 0),
            ("NSObject", 0),
            ("CCScheduler", 1),
            ("CustomScheduler", 2),
            ("CustomScheduler", 5),
            ("CCScheduler", 1),
            ("CCSchedulerHelper", 1),
            ("CCNode", 1),
            ("CCActionManager", 1),
            ("CustomActionManager", 8),
            ("CustomActionManager", 11),
            ("CCActionManager", 1),
            ("CCActionManagerHelper", 1),
        ];
        for class in [2, 3, 4, 5, 8, 9, 10, 11] {
            assert!(has_cocos_manager_ancestor(class, 0, |i| Some(classes[i])));
        }
        for class in [0, 1, 6, 7, 12] {
            assert!(!has_cocos_manager_ancestor(class, 0, |i| Some(classes[i])));
        }
    }

    #[test]
    fn incomplete_or_cyclic_class_chains_fail_closed() {
        assert!(!has_cocos_manager_ancestor(1, 0, |_| None));
        assert!(!has_cocos_manager_ancestor(1, 0, |_| Some(("Cycle", 1))));
    }
}
