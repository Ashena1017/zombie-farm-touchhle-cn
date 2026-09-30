/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSNotificationCenter`.

use super::ns_notification::NSNotificationName;
use super::ns_string;

use crate::objc::{
    id, msg, msg_class, msg_send, nil, objc_classes, release, retain, Class, ClassExports,
    HostObject, ObjC, NSZonePtr, SEL,
};
use crate::Environment;
use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct State {
    default_center: Option<id>,
    pub zombie_farm_startup_player_determined: bool,
}

pub fn zombie_farm_startup_player_determined(env: &Environment) -> bool {
    env.framework_state
        .foundation
        .ns_notification_center
        .zombie_farm_startup_player_determined
}

fn is_zombie_farm_bundle(bundle_id: &str) -> bool {
    bundle_id.starts_with("com.playforge.ZombieFarm") || bundle_id.starts_with("com.playforge.ZFR")
}

#[derive(Clone)]
struct Observer {
    observer: id,
    selector: SEL,
    object: id,
    /// Class `observer` had when it was registered, and whether the emulator
    /// was managing it as an object at that point. Used by
    /// [`observer_is_stale`] to recognise entries whose object has since been
    /// deallocated.
    registered_class: Class,
    was_host_managed: bool,
}

/// Whether this observer entry is a leftover for an object that was
/// deallocated while it was still registered.
///
/// `NSNotificationCenter` does not own its observers, and iOS 9 and later
/// remove observers that are deallocated while registered ("If you forget or
/// are unable to remove an observer, the system cleans up the next time it
/// would have posted to it"). Apps rely on that: Zombie Farm's quest system
/// registers every `ZFQuestRequirement` object for `incrementCount:`, and the
/// objects can be deallocated while still registered. Without this cleanup the
/// entry stays in the table as a dangling guest pointer, and by the time the
/// notification is posted the address usually holds an unrelated object, so
/// the observation selector is sent to the wrong object and emulation aborts
/// (observed as `Object 0x… (class "_touchHLE_NSString") does not respond to
/// selector "incrementCount:"`).
fn observer_is_stale(
    env: &Environment,
    observer: id,
    registered_class: Class,
    was_host_managed: bool,
) -> bool {
    if !was_host_managed {
        // We were never able to tell this object apart, so we cannot tell
        // whether it is still alive. Assume it is.
        return false;
    }
    if env.objc.get_host_object(observer).is_none() {
        // Deallocated, and its address has not been reused (yet).
        return true;
    }
    // Something is alive at that address, but is it the same object? Guest
    // addresses are reused, so a different class means a different object.
    ObjC::read_isa(observer, &env.mem) != registered_class
}

fn class_name(env: &Environment, class: Class) -> String {
    env.objc
        .try_get_class_name(class)
        .map(|name| name.to_string())
        .unwrap_or_else(|| format!("{class:?}"))
}

fn observer_description(
    env: &Environment,
    observer: id,
    registered_class: Class,
    was_host_managed: bool,
) -> String {
    let now = if was_host_managed && env.objc.get_host_object(observer).is_none() {
        "now deallocated".to_string()
    } else {
        format!(
            "now a live {}",
            class_name(env, ObjC::read_isa(observer, &env.mem))
        )
    };
    format!(
        "{:?} (registered as {}, {})",
        observer,
        class_name(env, registered_class),
        now,
    )
}

/// `TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE=1` disables the cleanup of
/// stale observers, for A/B-testing the workaround.
fn stale_observer_pruning_disabled() -> bool {
    static DISABLED: OnceLock<bool> = OnceLock::new();
    *DISABLED.get_or_init(|| {
        matches!(
            std::env::var("TOUCHHLE_NSNOTIFICATIONCENTER_NO_STALE_PRUNE")
                .ok()
                .as_deref(),
            Some("1") | Some("true") | Some("yes")
        )
    })
}

/// `TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT=<seconds>` logs a summary of how
/// many registered observers are stale, the first time a notification is
/// posted after each interval elapses. Diagnostic only.
fn stale_observer_audit_if_due(env: &mut Environment, center: id) {
    static NEXT_AUDIT: OnceLock<Mutex<Option<Instant>>> = OnceLock::new();
    let Some(interval) = std::env::var("TOUCHHLE_NSNOTIFICATIONCENTER_STALE_AUDIT")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|seconds| *seconds > 0)
    else {
        return;
    };
    let interval = Duration::from_secs(interval);

    let now = Instant::now();
    let next_audit = NEXT_AUDIT.get_or_init(|| Mutex::new(None));
    {
        let mut next_audit = next_audit.lock().unwrap();
        match *next_audit {
            Some(due) if now < due => return,
            _ => *next_audit = Some(now + interval),
        }
    }

    let host_obj = env.objc.borrow::<NSNotificationCenterHostObject>(center);
    let mut total = 0usize;
    let mut stale = Vec::new();
    for (name, observers) in host_obj.observers.iter() {
        for observer in observers {
            total += 1;
            if observer_is_stale(
                env,
                observer.observer,
                observer.registered_class,
                observer.was_host_managed,
            ) {
                stale.push(format!(
                    "  name {:?}, selector \"{}\", {}",
                    name,
                    observer.selector.as_str(&env.mem),
                    observer_description(
                        env,
                        observer.observer,
                        observer.registered_class,
                        observer.was_host_managed,
                    ),
                ));
            }
        }
    }
    log!(
        "NSNotificationCenter stale audit: {} registered observer(s), {} stale",
        total,
        stale.len()
    );
    for line in stale.iter().take(20) {
        log!("{line}");
    }
}

/// Diagnostic hooks for reproducing quest-system bugs in Zombie Farm. All of
/// them are inert unless the corresponding environment variable is set:
///
/// * `TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER=<seconds>` runs the
///   complete-all-quests cheat once, that many seconds after the first
///   notification is posted and once the quest system is listening.
/// * `TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION=<name>[,<name>...]` posts those
///   notifications on the default center,
///   `TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION_AFTER` (default 30) seconds later.
/// Whether the guest's quest system has registered any `incrementCount:`
/// observers yet, i.e. whether `-[ZFQuestNotification startListening]` has run.
fn zombie_farm_quest_observers_registered(env: &Environment) -> bool {
    let Some(center) = env
        .framework_state
        .foundation
        .ns_notification_center
        .default_center
    else {
        return false;
    };
    if env.objc.get_host_object(center).is_none() {
        return false;
    }
    let host_obj = env.objc.borrow::<NSNotificationCenterHostObject>(center);
    host_obj
        .observers
        .values()
        .flatten()
        .any(|observer| observer.selector.as_str(&env.mem) == "incrementCount:")
}

fn zombie_farm_debug_hooks(env: &mut Environment) {
    static START: OnceLock<Instant> = OnceLock::new();
    static QUESTS_COMPLETED_AT: OnceLock<Instant> = OnceLock::new();
    static POSTED: AtomicBool = AtomicBool::new(false);

    if !is_zombie_farm_bundle(env.bundle.bundle_identifier()) {
        return;
    }
    let complete_after = env_seconds("TOUCHHLE_ZFR_DEBUG_COMPLETE_QUESTS_AFTER");
    let post_names = std::env::var("TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION").ok();
    if complete_after.is_none() && post_names.is_none() {
        return;
    }
    let start = *START.get_or_init(Instant::now);
    let elapsed = start.elapsed().as_secs();

    if let Some(after) = complete_after {
        if elapsed >= after
            && QUESTS_COMPLETED_AT.get().is_none()
            && zombie_farm_quest_observers_registered(env)
        {
            QUESTS_COMPLETED_AT.get_or_init(Instant::now);
            log!("ZombieFarm debug: completing all quests {elapsed}s after the first notification");
            crate::objc::zombie_farm_complete_all_quests_cheat(env);
        }
    }

    if let Some(post_names) = post_names {
        let after = env_seconds("TOUCHHLE_ZFR_DEBUG_POST_NOTIFICATION_AFTER").unwrap_or(30);
        let ready = match QUESTS_COMPLETED_AT.get() {
            // Post a while after the quests were completed.
            Some(completed_at) => completed_at.elapsed().as_secs() >= after,
            // No quest-completion step configured: just wait after startup.
            None => complete_after.is_none() && start.elapsed().as_secs() >= after,
        };
        if ready && !POSTED.swap(true, Ordering::Relaxed) {
            log!("ZombieFarm debug: posting notifications {post_names:?} {elapsed}s after the first notification");
            let center_class = env.objc.get_known_class("NSNotificationCenter", &mut env.mem);
            let default_center_sel = env.objc.lookup_selector("defaultCenter").unwrap();
            let center: id = msg_send(env, (center_class, default_center_sel));
            let post_sel = env
                .objc
                .lookup_selector("postNotificationName:object:")
                .unwrap();
            for name in post_names.split(',').map(str::trim).filter(|n| !n.is_empty()) {
                let name: id = ns_string::from_rust_string(env, name.to_string());
                let _: () = msg_send(env, (center, post_sel, name, nil));
            }
        }
    }
}

/// `TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST=1` runs a one-shot self-test of
/// the stale-observer cleanup, the first time the guest registers an observer.
///
/// It registers a throwaway observer, deallocates it without removing it (which
/// is what Zombie Farm's quest requirements end up doing), allocates some
/// strings so the freed memory is likely reused, and then posts the
/// notification. Without the cleanup this aborts emulation with
/// `... does not respond to selector "incrementCount:"`; with it, the entry is
/// dropped and a warning is logged. Diagnostic only.
fn stale_observer_self_test(env: &mut Environment, center: id) {
    static RAN: AtomicBool = AtomicBool::new(false);
    if !matches!(
        std::env::var("TOUCHHLE_NSNOTIFICATIONCENTER_STALE_SELFTEST")
            .ok()
            .as_deref(),
        Some("1") | Some("true") | Some("yes")
    ) {
        return;
    }
    if RAN.swap(true, Ordering::Relaxed) {
        return;
    }
    let Some(selector) = env.objc.lookup_selector("incrementCount:") else {
        log!("NSNotificationCenter self-test: no incrementCount: selector, skipping");
        return;
    };
    let name = "TOUCHHLE_STALE_OBSERVER_SELFTEST";

    let victim: id = msg_class![env; NSObject alloc];
    let victim_class = ObjC::read_isa(victim, &env.mem);
    let name_object: id = ns_string::from_rust_string(env, name.to_string());
    log!(
        "NSNotificationCenter self-test: registering throwaway observer {:?} ({}) for \"{}\"",
        victim,
        class_name(env, victim_class),
        name,
    );
    let _: () = msg![env; center addObserver:victim
                              selector:selector
                                  name:name_object
                                object:nil];

    // Deallocate it while it is still registered, exactly like a quest
    // requirement that is released without `stopListening`.
    release(env, victim);
    // Then allocate strings, so that the freed address is likely to be reused by
    // an unrelated object - that is the situation that makes the real crash
    // report an NSString.
    for _ in 0..8 {
        let junk: id = ns_string::from_rust_string(env, "stale observer self-test".to_string());
        release(env, junk);
    }
    let now = if env.objc.get_host_object(victim).is_some() {
        format!(
            "its address is now a live {}",
            class_name(env, ObjC::read_isa(victim, &env.mem))
        )
    } else {
        "its address is still free".to_string()
    };
    log!(
        "NSNotificationCenter self-test: observer {victim:?} was deallocated, {now}; posting \"{name}\""
    );
    let _: () = msg![env; center postNotificationName:name_object
                                              object:nil];
    log!("NSNotificationCenter self-test: the notification was posted without aborting emulation");
}

fn env_seconds(name: &str) -> Option<u64> {
    std::env::var(name).ok().and_then(|value| value.parse().ok())
}

fn notification_center_state(env: &Environment) -> &NSNotificationCenterHostObject {
    let center: id = env
        .framework_state
        .foundation
        .ns_notification_center
        .default_center
        .unwrap();
    env.objc.borrow::<NSNotificationCenterHostObject>(center)
}

#[allow(dead_code)]
fn debug_dump_all_observers(env: &Environment) -> usize {
    notification_center_state(env)
        .observers
        .values()
        .map(|observers| observers.len())
        .sum()
}



struct NSNotificationCenterHostObject {
    observers: HashMap<Option<Cow<'static, str>>, Vec<Observer>>,
}
impl HostObject for NSNotificationCenterHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSNotificationCenter: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSNotificationCenterHostObject {
        observers: HashMap::new(),
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)defaultCenter {
    if let Some(c) = env.framework_state.foundation.ns_notification_center.default_center {
        c
    } else {
        let new: id = msg![env; this new];
        env.framework_state.foundation.ns_notification_center.default_center = Some(new);
        new
    }
}

- (())dealloc {
    let host_obj = env.objc.borrow_mut::<NSNotificationCenterHostObject>(this);
    let observers = std::mem::take(&mut host_obj.observers);
    for observer in observers.values().flatten() {
        release(env, observer.object);
    }
    env.objc.dealloc_object(this, &mut env.mem);
}

- (())addObserver:(id)observer
         selector:(SEL)selector
             name:(NSNotificationName)name
           object:(id)object {
    if observer == nil {
        log_dbg!(
            "Ignoring addObserver:selector:name:object: with nil observer for {:?}",
            selector.as_str(&env.mem),
        );
        return;
    }

    if name == nil &&
        env.bundle.bundle_identifier().starts_with("com.chillingo.cuttherope") &&
        selector == env.objc.lookup_selector("fetchUpdateNotification:").unwrap() {
        // As we nullified Flurry SDK, we also need to no-op
        // related notifications
        log!("Applying game-specific hack for Cut the Rope: ignoring addObserver:selector:name:object: for fetchUpdateNotification:");
        return;
    }
    // nil means the observer wants notifications with any name.
    // Usually a static string, so no real copy will happen.
    let name = if name == nil {
        None
    } else {
        Some(ns_string::to_rust_string(env, name))
    };

    log_dbg!(
        "[(NSNotificationCenter*){:?} addObserver:{:?} selector:{:?} name:{:?} object:{:?}",
        this,
        observer,
        selector,
        name,
        object,
    );

    // When adding an observer, only the object is retained so it doesn't get
    // deallocated before the notification is delivered. Some apps, such as
    // Dungeon Hunter 2, rely on this being the case.
    // The observer is not retained to avoid retain cycles.
    // https://stackoverflow.com/a/36582937
    // While not explicitly stated by the documentation, there's a paragraph
    // that hints at this behavior:
    // "If your app targets iOS 9.0 and later or macOS 10.11 and later, you do
    // not need to unregister an observer that you created with this function.
    // If you forget or are unable to remove an observer, the system cleans up
    // the next time it would have posted to it."
    // https://developer.apple.com/documentation/foundation/notificationcenter/addobserver(_:selector:name:object:)?language=objc
    // Implying that prior to these versions, it's unsafe to not remove an
    // observer. It's been observed that some apps expect and rely on this
    // behavior, such as Marmalade SDK games that use the Movie Player
    // (Pandemonium and COD Zombies, for example).

    retain(env, object);

    // Remember what the observer looked like, so that entries left behind by
    // objects that are deallocated without being removed can be recognised
    // later. See `observer_is_stale`.
    let was_host_managed = env.objc.get_host_object(observer).is_some();
    let registered_class = ObjC::read_isa(observer, &env.mem);

    let host_obj = env.objc.borrow_mut::<NSNotificationCenterHostObject>(this);
    host_obj.observers.entry(name).or_default().push(Observer {
        observer,
        selector,
        object,
        registered_class,
        was_host_managed,
    });

    stale_observer_self_test(env, this);
}

- (())removeObserver:(id)observer {
    msg![env; this removeObserver:observer name:nil object:nil]
}

- (())removeObserver:(id)observer
                name:(NSNotificationName)name
              object:(id)object {
    assert!(observer != nil); // TODO

    let name = if name == nil {
        None
    } else {
        // Usually a static string, so no real copy will happen
        Some(ns_string::to_rust_string(env, name))
    };

    log_dbg!(
        "[(NSNotificationCenter*){:?} removeObserver:{:?} name:{:?} object:{:?}",
        this,
        observer,
        name,
        object,
    );

    // TODO: is this the correct behaviour, can an observer be registered
    // several times?
    let mut removed_observers = Vec::new();

    let host_obj = env.objc.borrow_mut::<NSNotificationCenterHostObject>(this);
    if let Some(name) = name {
        let Some(observers) = host_obj.observers.get_mut(&Some(name)) else {
            return;
        };
        remove_observers_internal(observers, &mut removed_observers, observer, object);
    } else {
        for observers in host_obj.observers.values_mut() {
            remove_observers_internal(observers, &mut removed_observers, observer, object);
        }
    };

    for removed_observer in removed_observers {
        release(env, removed_observer.object);
    }
}

- (())postNotification:(id)notification {
    log_dbg!(
        "[(NSNotificationCenter*){:?} postNotification:{:?}]",
        this,
        notification,
    );

    let name: id = msg![env; notification name];
    // Usually a static string, so no real copy will happen
    let name = ns_string::to_rust_string(env, name);

    let notification_poster: id = msg![env; notification object];

    if name == "kStartupPlayerDeterminedNotification"
        && is_zombie_farm_bundle(env.bundle.bundle_identifier())
    {
        env.framework_state
            .foundation
            .ns_notification_center
            .zombie_farm_startup_player_determined = true;
    }

    log_dbg!(
        "ZombieFarm trace: notification {:?} posted by {:?}",
        name,
        notification_poster
    );

    stale_observer_audit_if_due(env, this);
    zombie_farm_debug_hooks(env);

    let host_obj = env.objc.borrow_mut::<NSNotificationCenterHostObject>(this);
    let mut observers = Vec::new();
    if let Some(named_observers) = host_obj.observers.get(&Some(name.clone())) {
        observers.extend(named_observers.iter().cloned());
    }
    if let Some(any_name_observers) = host_obj.observers.get(&None) {
        observers.extend(any_name_observers.iter().cloned());
    }
    let bundle_id = env.bundle.bundle_identifier();
    if observers.is_empty()
        && name == "kStatusBarCanceledNotification"
        && is_zombie_farm_bundle(bundle_id)
    {
        let status_bar_class = env.objc.get_known_class("StatusBar", &mut env.mem);
        let hide_sel = env.objc.lookup_selector("hide").unwrap();
        log!("ZombieFarm trace: no observer for cancel notification; hiding StatusBar");
        let _: () = msg_send(env, (status_bar_class, hide_sel));
        let status_bar_sel = env.objc.lookup_selector("statusBar").unwrap();
        let status_bar: id = msg_send(env, (status_bar_class, status_bar_sel));
        if status_bar != nil {
            let view: id = msg![env; status_bar view];
            if view != nil {
                () = msg![env; view setHidden:true];
                () = msg![env; view setUserInteractionEnabled:false];
                () = msg![env; view removeFromSuperview];
            }
        }
        return;
    }
    let mut stale_observers: Vec<(id, Class, bool)> = Vec::new();
    for Observer {
        observer,
        selector,
        object,
        registered_class,
        was_host_managed,
    } in observers
    {
        if observer == nil {
            continue;
        }

        // The object argument is a filter for which notification sources the
        // observer is interested in.
        if object != nil && notification_poster != object {
            continue;
        }

        if !stale_observer_pruning_disabled()
            && observer_is_stale(env, observer, registered_class, was_host_managed)
        {
            log!(
                "Skipping stale NSNotificationCenter observer for \"{}\" on notification {:?}: {}",
                selector.as_str(&env.mem),
                name,
                observer_description(env, observer, registered_class, was_host_managed),
            );
            stale_observers.push((observer, registered_class, was_host_managed));
            continue;
        }

        log_dbg!(
            "Notification {:?} observed, sending {:?} message to {:?}",
            notification,
            selector.as_str(&env.mem),
            observer
        );
        log_dbg!(
            "ZombieFarm trace: notification {:?} observed, sending {:?} to {:?}",
            name,
            selector.as_str(&env.mem),
            observer
        );

        // In some cases, observer could be removed during the
        // processing of the notification, effectively releasing it.
        // (This is happening with Spore Origins)
        // We need to retain it for correctness.
        retain(env, observer);
        // Signature should be `- (void)notification:(NSNotification *)notif`.
        let _: () = msg_send(env, (observer, selector, notification));
        release(env, observer);
    }

    if !stale_observers.is_empty() {
        // Drop the entries so that the table doesn't keep growing, and balance
        // the retain that was taken on the filter objects. Match on the whole
        // entry, not just the address: guest code that ran during the dispatch
        // above may have re-registered an object, and only the exact stale
        // entry should go.
        let mut removed_observers = Vec::new();
        {
            let host_obj = env.objc.borrow_mut::<NSNotificationCenterHostObject>(this);
            for observers in host_obj.observers.values_mut() {
                let mut i = 0;
                while i < observers.len() {
                    let observer = &observers[i];
                    let key = (
                        observer.observer,
                        observer.registered_class,
                        observer.was_host_managed,
                    );
                    if stale_observers.contains(&key) {
                        removed_observers.push(observers.swap_remove(i));
                    } else {
                        i += 1;
                    }
                }
            }
        }
        for removed_observer in removed_observers {
            release(env, removed_observer.object);
        }
    }
}
- (())postNotificationName:(NSNotificationName)name
                    object:(id)object {
    msg![env; this postNotificationName:name
                                 object:object
                               userInfo:nil]
}
- (())postNotificationName:(NSNotificationName)name
                    object:(id)object
                  userInfo:(id)user_info { // NSDictionary*
    let notification: id = msg_class![env; NSNotification alloc];
    let notification: id = msg![env; notification initWithName:name
                                                        object:object
                                                      userInfo:user_info];
    let _: () = msg![env; this postNotification:notification];
    release(env, notification);
}

@end

};

/// A helper function to populate `removed_observers` with observers
/// removed from `observers` based on `observer` and `object` criteria.
fn remove_observers_internal(
    observers: &mut Vec<Observer>,
    removed_observers: &mut Vec<Observer>,
    observer: id,
    object: id,
) {
    let mut i = 0;
    while i < observers.len() {
        if observers[i].observer == observer && (object == nil || object == observers[i].object) {
            removed_observers.push(observers.swap_remove(i));
        } else {
            i += 1;
        }
    }
}
