/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Handling of Objective-C messaging (`objc_msgSend` and friends).
//!
//! Resources:
//! - Apple's [Objective-C Runtime Programming Guide](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ObjCRuntimeGuide/Articles/ocrtHowMessagingWorks.html)
//! - [Apple's documentation of `objc_msgSend`](https://developer.apple.com/documentation/objectivec/1456712-objc_msgsend)
//! - Mike Ash's [objc_msgSend's New Prototype](https://www.mikeash.com/pyblog/objc_msgsends-new-prototype.html)
//! - Peter Steinberger's [Calling Super at Runtime in Swift](https://steipete.com/posts/calling-super-at-runtime/) explains `objc_msgSendSuper2`

use super::{id, nil, Class, ObjC, IMP, SEL};
use crate::abi::{CallFromHost, GuestRet};
use crate::cpu::Cpu;
use crate::environment::ThreadId;
use crate::libc::pthread::cond::{
    pthread_cond_broadcast, pthread_cond_destroy, pthread_cond_init, pthread_cond_t,
    pthread_cond_wait,
};
use crate::libc::pthread::mutex::{
    pthread_mutex_destroy, pthread_mutex_init, pthread_mutex_lock, pthread_mutex_t,
    pthread_mutex_unlock,
};
use crate::mem::{guest_size_of, ConstPtr, MutPtr, MutVoidPtr, SafeRead};
use crate::objc::classes::InitializationStatus;
use crate::Environment;
use std::any::TypeId;
use std::sync::atomic::Ordering;

pub(super) struct ThreadInitializer {
    mutex: MutPtr<pthread_mutex_t>,
    cond: MutPtr<pthread_cond_t>,
    tid: ThreadId,
    waiters: u32,
}

fn maybe_initialize_class(env: &mut Environment, receiver: id) {
    let Some(class_host_object) = env.objc.get_host_object(receiver) else {
        return;
    };
    let Some(&super::ClassHostObject {
        superclass,
        is_metaclass,
        is_initialized,
        ..
    }) = class_host_object.as_any().downcast_ref()
    else {
        // If it's here, there's one of two cases:
        //
        // 1: The receiver is an instance. The class should then have already
        // called +initialize since you need to call +alloc to create an
        // instance (this also needs to be upheld for instances created with
        // class_createInstance(), whenever we implement that)
        //
        // 2: The reciever is a fake/unimplemented class. There's no reason to
        // send +initialize to those, so we don't bother.
        return;
    };

    if is_metaclass || is_initialized == InitializationStatus::Initialized {
        // On the offchance that this is a metaclass, we don't need to send
        // +initialize to it. We also don't need to send it if the class is
        // already initialized.
        return;
    }

    // This class is not initialized, but there might be classes above it in the
    // hierarchy that also need to be checked, so check those first.
    if !superclass.is_null() {
        maybe_initialize_class(env, superclass);
    }

    if is_initialized == InitializationStatus::Initializing {
        env.objc
            .initializer_threads
            .get_mut(&receiver)
            .unwrap()
            .waiters += 1;
        let ThreadInitializer {
            mutex, cond, tid, ..
        } = *env.objc.initializer_threads.get(&receiver).unwrap();

        // The current thread is already initializing, so let it call other
        // messages while it does so.
        if tid == env.current_thread {
            return;
        }

        // We are waiting for another thread to initialize, wait for it to
        // broadcast that it has finished.
        pthread_mutex_lock(env, mutex);
        loop {
            let class_host_object = env.objc.get_host_object(receiver).unwrap();
            let &super::ClassHostObject { is_initialized, .. } =
                class_host_object.as_any().downcast_ref().unwrap();
            if is_initialized == InitializationStatus::Initialized {
                break;
            }
            pthread_cond_wait(env, cond, mutex);
        }
        pthread_mutex_unlock(env, mutex);

        let ThreadInitializer {
            ref mut waiters, ..
        } = *env.objc.initializer_threads.get_mut(&receiver).unwrap();
        *waiters -= 1;
        if *waiters == 0 {
            // We're the last waiter for this initialize, so clean up state on
            // the way out.
            pthread_cond_destroy(env, cond);
            pthread_mutex_destroy(env, mutex);
            env.objc.initializer_threads.remove(&receiver);
        }
    } else {
        log_dbg!(
            "Initializing {:?} on thread {}",
            env.objc.try_get_class_name(receiver),
            env.current_thread
        );
        let regs = *env.cpu.regs();

        let mutex = env.mem.alloc(guest_size_of::<pthread_mutex_t>()).cast();
        let cond = env.mem.alloc(guest_size_of::<pthread_cond_t>()).cast();
        pthread_mutex_init(env, mutex, ConstPtr::null());
        pthread_cond_init(env, cond, ConstPtr::null());
        env.objc.initializer_threads.insert(
            receiver,
            ThreadInitializer {
                mutex,
                cond,
                tid: env.current_thread,
                waiters: 0,
            },
        );

        let super::ClassHostObject { is_initialized, .. } = env.objc.borrow_mut(receiver);
        *is_initialized = InitializationStatus::Initializing;
        () = msg![env; receiver initialize];
        let super::ClassHostObject { is_initialized, .. } = env.objc.borrow_mut(receiver);
        *is_initialized = InitializationStatus::Initialized;
        env.cpu.regs_mut().copy_from_slice(&regs);
        log_dbg!(
            "Done initializing {:?} on thread {}",
            env.objc.try_get_class_name(receiver),
            env.current_thread
        );
        if env.objc.initializer_threads.get(&receiver).unwrap().waiters == 0 {
            // Nobody ended up waiting for this initializer, so we can just
            // destroy it.
            pthread_cond_destroy(env, cond);
            pthread_mutex_destroy(env, mutex);
            env.objc.initializer_threads.remove(&receiver);
        } else {
            pthread_mutex_lock(env, mutex);
            pthread_cond_broadcast(env, cond);
            pthread_mutex_unlock(env, mutex);
        }
    }
}

mod zombie_farm;

pub use zombie_farm::zombie_farm_complete_all_quests_cheat;
pub use zombie_farm::zombie_farm_zoom_step;
use zombie_farm::{
    trace_zombie_farm_daily_message, trace_zombie_farm_layout_message,
    trace_zombie_farm_layout_normal_return, trace_zombie_farm_layout_stret_return,
    trace_zombie_farm_layout_to_console, trace_zombie_farm_quest_message,
    trace_zombie_farm_quest_normal_return, trace_zombie_farm_status_message,
    trace_zombie_farm_status_normal_return, zombie_farm_begin_zombie_cell_assignment,
    zombie_farm_cell_content_size_override, zombie_farm_daily_trace_enabled,
    zombie_farm_finish_zombie_cell_assignment, zombie_farm_ignore_spurious_operation_done,
    zombie_farm_layout_arg_details, zombie_farm_log_quest_object_state,
    zombie_farm_log_status_object_state, zombie_farm_needs_post_dispatch_workarounds,
    zombie_farm_needs_pre_dispatch_workarounds, zombie_farm_post_dispatch_workarounds,
    zombie_farm_pre_dispatch_workarounds, zombie_farm_prepare_cctable_cell,
    zombie_farm_quest_arg_details, zombie_farm_quest_trace_enabled,
    zombie_farm_return_nil_for_stale_object_message,
    zombie_farm_should_return_self_for_unimplemented_cocos_reverse, zombie_farm_status_arg_details,
    zombie_farm_status_trace_enabled, zombie_farm_tag_summary_win_size_override,
    zombie_farm_uses_playforge_bundle, ZOMBIE_FARM_APPLY_TRACE_DEPTH,
};

/// The core implementation of `objc_msgSend`, the main function of Objective-C.
///
/// Note that while only two parameters (usually receiver and selector) are
/// defined by the wrappers over this function, a call to an `objc_msgSend`
/// variant may have additional arguments to be forwarded (or rather, left
/// untouched) by `objc_msgSend` when it tail-calls the method implementation it
/// looks up. This is invisible to the Rust type system; we're relying on
/// [crate::abi::CallFromGuest] here.
///
/// Similarly, the return value of `objc_msgSend` is whatever value is returned
/// by the method implementation. We are relying on CallFromGuest not
/// overwriting it.
#[allow(non_snake_case)]
fn objc_msgSend_inner(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    super2: Option<Class>,
    tolerate_type_mismatch: bool,
) {
    let _profile = crate::zfr_profile::scope(crate::zfr_profile::Category::ObjcMsgSend);
    let selector_name = env.objc.selector_name(selector, &env.mem);
    log_dbg!("Dispatching {} for {:?}", selector_name, receiver);
    let message_type_info = env.objc.message_type_info.take();

    if receiver == nil {
        // https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ObjectiveC/Chapters/ocObjectsClasses.html#//apple_ref/doc/uid/TP30001163-CH11-SW7
        log_dbg!("[nil {}]", selector_name);
        env.cpu.regs_mut()[0..2].fill(0);
        return;
    }
    if receiver.to_bits() < env.mem.null_segment_size() || receiver.to_bits() % 4 != 0 {
        if selector_name == "compare:" {
            log_dbg!(
                "Ignoring compare: sent to invalid low ObjC pointer {:?}",
                receiver
            );
        } else if zombie_farm_uses_playforge_bundle(env) {
            log!(
                "Warning: ignoring {} sent to invalid low ObjC pointer {:?} (guest LR=0x{:08x}, PC=0x{:08x})",
                selector_name,
                receiver,
                env.cpu.regs()[Cpu::LR],
                env.cpu.regs()[Cpu::PC],
            );
        } else {
            log!(
                "Warning: ignoring {} sent to invalid low ObjC pointer {:?}",
                selector_name,
                receiver
            );
        }
        env.cpu.regs_mut()[0..2].fill(0);
        return;
    }

    if zombie_farm_uses_playforge_bundle(env)
        && matches!(selector_name, "release" | "retain" | "autorelease")
        && env.objc.get_host_object(receiver).is_none()
    {
        log_dbg!(
            "ZombieFarm workaround: ignoring {} sent to stale unregistered object {:?}",
            selector_name,
            receiver
        );
        if selector_name != "release" {
            env.cpu.regs_mut()[0] = receiver.to_bits();
        }
        return;
    }

    let orig_class = super2.unwrap_or_else(|| ObjC::read_isa(receiver, &env.mem));
    if zombie_farm_uses_playforge_bundle(env) || crate::objc::last_message_debug_enabled() {
        let debug = crate::objc::ObjCMessageDebug {
            receiver,
            selector,
            receiver_class: (orig_class != nil).then_some(orig_class),
        };
        env.objc.last_message_debug = Some(debug);
        crate::objc::set_global_last_message_debug(debug);
        if zombie_farm_uses_playforge_bundle(env) {
            crate::objc::record_zombie_farm_message_trace(
                debug,
                selector_name,
                env.cpu.regs(),
                env.cpu.cpsr(),
            );
        }
    }
    if orig_class == nil {
        if matches!(selector_name, "release" | "retain" | "autorelease") {
            log!(
                "Warning: ignoring {} sent to object {:?} with nil isa",
                selector_name,
                receiver
            );
            return;
        }
        if selector_name == "retainCount" {
            log!(
                "Warning: returning 0 for retainCount sent to object {:?} with nil isa",
                receiver
            );
            env.cpu.regs_mut()[0..2].fill(0);
            return;
        }
        if zombie_farm_ignore_spurious_operation_done(env, receiver, selector_name) {
            return;
        }
        if zombie_farm_return_nil_for_stale_object_message(
            env,
            receiver,
            selector_name,
            "nil-isa object",
        ) {
            return;
        }
        panic!(
            "Receiver {:?} for selector \"{}\" has nil isa",
            receiver, selector_name
        );
    }
    maybe_initialize_class(env, receiver);

    if zombie_farm_needs_pre_dispatch_workarounds(env, selector_name)
        && zombie_farm_pre_dispatch_workarounds(env, receiver, selector, selector_name)
    {
        return;
    }
    let regs_before_zombie_farm_prepare = *env.cpu.regs();
    if selector_name == "_setIndex:forCell:" {
        zombie_farm_prepare_cctable_cell(env, receiver, selector);
    }
    env.cpu
        .regs_mut()
        .copy_from_slice(&regs_before_zombie_farm_prepare);

    // Traverse the chain of superclasses to find the method implementation.

    let super_lookup = super2.is_some();
    let cached_method = env
        .objc
        .lookup_cached_method_class(orig_class, selector, super_lookup);
    let mut class = if let Some(cached_method) = cached_method {
        crate::zfr_profile::count(crate::zfr_profile::Category::ObjcMsgCacheHit);
        cached_method.implementation_class
    } else {
        crate::zfr_profile::count(crate::zfr_profile::Category::ObjcMsgCacheMiss);
        orig_class
    };
    let mut using_cached_method_class = cached_method.is_some();
    loop {
        if class == nil {
            assert!(class != orig_class);

            let class_host_object = env.objc.get_host_object(orig_class).unwrap();
            let &super::ClassHostObject {
                ref name,
                is_metaclass,
                ..
            } = class_host_object.as_any().downcast_ref().unwrap();

            panic!(
                "{} {:?} ({}class \"{}\", {:?}){} does not respond to selector \"{}\"!",
                if is_metaclass { "Class" } else { "Object" },
                receiver,
                if is_metaclass { "meta" } else { "" },
                name,
                orig_class,
                if super2.is_some() {
                    "'s superclass"
                } else {
                    ""
                },
                selector.as_str(&env.mem),
            );
        }

        let Some(host_object) = env.objc.get_host_object(class) else {
            if using_cached_method_class {
                env.objc
                    .remove_cached_method_class(orig_class, selector, super_lookup);
                class = orig_class;
                using_cached_method_class = false;
                continue;
            }
            let selector_name = selector.as_str(&env.mem).to_string();
            if matches!(selector_name.as_str(), "release" | "retain" | "autorelease") {
                if zombie_farm_uses_playforge_bundle(env) {
                    log!(
                        "Warning: ignoring {} sent to object {:?} with unregistered class {:?} (guest LR=0x{:08x}, PC=0x{:08x})",
                        selector_name,
                        receiver,
                        class,
                        env.cpu.regs()[Cpu::LR],
                        env.cpu.regs()[Cpu::PC],
                    );
                } else {
                    log!(
                        "Warning: ignoring {} sent to object {:?} with unregistered class {:?}",
                        selector_name,
                        receiver,
                        class
                    );
                }
                if selector_name == "retain" || selector_name == "autorelease" {
                    env.cpu.regs_mut()[0] = receiver.to_bits();
                }
                return;
            }
            if zombie_farm_return_nil_for_stale_object_message(
                env,
                receiver,
                &selector_name,
                "unregistered-class object",
            ) {
                return;
            }
            panic!(
                "Receiver {:?} for selector \"{}\" has unregistered class {:?}",
                receiver, selector_name, class
            );
        };

        if let Some(&super::ClassHostObject {
            superclass,
            ref methods,
            ref name,
            ..
        }) = host_object.as_any().downcast_ref()
        {
            // Skip method lookup on first iteration if this is the super-call
            // variant of objc_msgSend (look up the superclass first)
            if !using_cached_method_class && super_lookup && class == orig_class {
                class = superclass;
                continue;
            }

            let imp = if using_cached_method_class {
                cached_method
                    .filter(|cached| cached.implementation_class == class)
                    .map(|cached| cached.imp)
            } else {
                methods.get(&selector).copied()
            };
            if let Some(imp) = imp {
                if !using_cached_method_class {
                    env.objc
                        .cache_method_class(orig_class, selector, super_lookup, class, imp);
                }
                log_dbg!("Found method on: {}", name);
                let zombie_farm_bundle = zombie_farm_uses_playforge_bundle(env);
                let zombie_farm_debug_enabled =
                    zombie_farm_bundle && crate::zombie_farm_debug::enabled();
                let zombie_farm_scroll_profile_enabled =
                    zombie_farm_bundle && crate::zombie_farm_debug::scroll_profile_enabled();
                let zombie_farm_status_trace_active = zombie_farm_bundle
                    && (zombie_farm_debug_enabled || zombie_farm_status_trace_enabled());
                let zombie_farm_daily_trace_active =
                    zombie_farm_bundle && zombie_farm_daily_trace_enabled();
                let zombie_farm_quest_trace_active =
                    zombie_farm_bundle && zombie_farm_quest_trace_enabled();
                let zombie_farm_cocos_label_text_selector = zombie_farm_bundle
                    && (selector_name == "setString:"
                        || selector_name.starts_with("initWithString:")
                        || selector_name.starts_with("labelWithString:"));
                let zombie_farm_reverse_workaround_candidate = zombie_farm_bundle
                    && selector_name == "reverse"
                    && matches!(
                        name.as_str(),
                        "CCAction" | "CCFiniteTimeAction" | "CCIntervalAction"
                    );
                let receiver_class_name = if zombie_farm_debug_enabled
                    || zombie_farm_scroll_profile_enabled
                    || zombie_farm_status_trace_active
                    || zombie_farm_daily_trace_active
                    || zombie_farm_quest_trace_active
                    || zombie_farm_cocos_label_text_selector
                    || zombie_farm_reverse_workaround_candidate
                {
                    env.objc.stable_class_name(orig_class).unwrap_or("unknown")
                } else {
                    "unknown"
                };
                if zombie_farm_debug_enabled {
                    crate::zombie_farm_debug::record_objc_message(
                        receiver,
                        receiver_class_name,
                        selector_name,
                        env.cpu.regs(),
                    );
                }
                let zombie_farm_scroll_profile_bucket = if zombie_farm_scroll_profile_enabled {
                    crate::zombie_farm_debug::scroll_profile_bucket(
                        receiver_class_name,
                        selector_name,
                    )
                    .or_else(|| {
                        crate::zombie_farm_debug::scroll_profile_bucket(name, selector_name)
                    })
                } else {
                    None
                };
                let trace_zombie_farm_layout = zombie_farm_debug_enabled
                    && (trace_zombie_farm_layout_message(receiver_class_name, selector_name)
                        || trace_zombie_farm_layout_message(name, selector_name));
                let trace_zombie_farm_status = (zombie_farm_status_trace_active
                    && (trace_zombie_farm_status_message(receiver_class_name, selector_name)
                        || trace_zombie_farm_status_message(name, selector_name)))
                    || (zombie_farm_daily_trace_active
                        && trace_zombie_farm_daily_message(selector_name));
                let trace_zombie_farm_quest = zombie_farm_quest_trace_active
                    && (trace_zombie_farm_quest_message(receiver_class_name, selector_name)
                        || trace_zombie_farm_quest_message(name, selector_name));
                let record_zombie_farm_hunger = zombie_farm_debug_enabled
                    && (crate::zombie_farm_debug::should_record_hunger_message(
                        receiver_class_name,
                        selector_name,
                    ) || crate::zombie_farm_debug::should_record_hunger_message(
                        name,
                        selector_name,
                    ));
                let trace_zombie_farm_apply_scope = zombie_farm_debug_enabled
                    && selector_name == "applyZombieHunger"
                    && (receiver_class_name == "ZFGuiLayer" || name == "ZFGuiLayer");
                let record_zombie_farm_apply_trace = zombie_farm_debug_enabled
                    && ZOMBIE_FARM_APPLY_TRACE_DEPTH.load(Ordering::Relaxed) > 0
                    && (crate::zombie_farm_debug::should_record_apply_trace_message(
                        receiver_class_name,
                        selector_name,
                    ) || crate::zombie_farm_debug::should_record_apply_trace_message(
                        name,
                        selector_name,
                    ));
                let record_zombie_farm_cocos_label_text = zombie_farm_cocos_label_text_selector
                    && (crate::zombie_farm_debug::should_record_cocos_label_text(
                        receiver_class_name,
                        selector_name,
                    ) || crate::zombie_farm_debug::should_record_cocos_label_text(
                        name,
                        selector_name,
                    ));
                if trace_zombie_farm_status || trace_zombie_farm_layout || trace_zombie_farm_quest {
                    let imp_description = match imp {
                        IMP::Host(_) => "host".to_string(),
                        IMP::Guest(guest_imp) => format!("{:?}", guest_imp),
                    };
                    let arg_description = if trace_zombie_farm_status {
                        zombie_farm_status_arg_details(selector_name, env.cpu.regs())
                    } else if trace_zombie_farm_quest {
                        zombie_farm_quest_arg_details(selector_name, env.cpu.regs())
                    } else {
                        zombie_farm_layout_arg_details(selector_name, env.cpu.regs())
                    }
                    .map(|arg| format!(" {}", arg))
                    .unwrap_or_default();
                    if trace_zombie_farm_status {
                        log!(
                            "ZombieFarm status: [{} {}] receiver {:?}, implementation class {}, imp {}{}",
                            receiver_class_name,
                            selector_name,
                            receiver,
                            name,
                            imp_description,
                            arg_description,
                        );
                    }
                    if trace_zombie_farm_layout {
                        crate::zombie_farm_debug::record_table_args(
                            receiver,
                            receiver_class_name,
                            selector_name,
                            env.cpu.regs(),
                        );
                        crate::zombie_farm_debug::record_layout_event(format!(
                            "[0x{:x} {} {}]{}",
                            receiver.to_bits(),
                            receiver_class_name,
                            selector_name,
                            arg_description
                        ));
                        if trace_zombie_farm_layout_to_console(selector_name) {
                            log_dbg!(
                                "ZombieFarm trace: [{} {}] receiver {:?}, implementation class {}, imp {}{}",
                                receiver_class_name,
                                selector_name,
                                receiver,
                                name,
                                imp_description,
                                arg_description,
                            );
                        }
                    }
                    if trace_zombie_farm_quest {
                        log!(
                            "ZombieFarm quest: [{} {}] receiver {:?}, implementation class {}, imp {}{}",
                            receiver_class_name,
                            selector_name,
                            receiver,
                            name,
                            imp_description,
                            arg_description,
                        );
                    }
                }
                let regs_before_zombie_farm_record = if record_zombie_farm_hunger
                    || record_zombie_farm_apply_trace
                    || record_zombie_farm_cocos_label_text
                {
                    Some(*env.cpu.regs())
                } else {
                    None
                };
                if record_zombie_farm_hunger || record_zombie_farm_apply_trace {
                    let regs_before = regs_before_zombie_farm_record.as_ref().unwrap();
                    if record_zombie_farm_hunger {
                        crate::zombie_farm_debug::record_hunger_message(
                            env,
                            receiver,
                            receiver_class_name,
                            selector_name,
                            regs_before,
                        );
                    }
                    if record_zombie_farm_apply_trace {
                        crate::zombie_farm_debug::record_apply_trace_message(
                            env,
                            receiver,
                            receiver_class_name,
                            selector_name,
                            regs_before,
                        );
                    }
                }
                let selector_name_for_after = selector_name;
                if trace_zombie_farm_apply_scope {
                    ZOMBIE_FARM_APPLY_TRACE_DEPTH.fetch_add(1, Ordering::Relaxed);
                }
                let zombie_farm_scroll_profile = zombie_farm_scroll_profile_bucket.map(|bucket| {
                    (
                        crate::zombie_farm_debug::begin_scroll_profile_call(
                            bucket,
                            receiver,
                            receiver_class_name,
                            selector_name,
                            env.cpu.regs(),
                        ),
                        std::time::Instant::now(),
                    )
                });
                let zombie_farm_cell_build_scope_started = zombie_farm_bundle
                    && zombie_farm_scroll_profile_enabled
                    && crate::zombie_farm_debug::begin_cell_build_scope(
                        selector_name,
                        env.cpu.regs(),
                    );
                let zombie_farm_zombie_cell_assignment_started = zombie_farm_bundle
                    && zombie_farm_begin_zombie_cell_assignment(
                        env,
                        receiver,
                        selector_name,
                        env.cpu.regs(),
                    );
                let zombie_farm_cell_build_profile = (zombie_farm_bundle
                    && zombie_farm_scroll_profile_enabled
                    && crate::zombie_farm_debug::cell_build_scope_active())
                .then(std::time::Instant::now);
                if zombie_farm_should_return_self_for_unimplemented_cocos_reverse(
                    zombie_farm_bundle,
                    receiver_class_name,
                    name,
                    selector_name,
                ) {
                    log!(
                        "ZombieFarm workaround: returning self for unimplemented [{} reverse] using {}",
                        receiver_class_name,
                        name
                    );
                    env.cpu.regs_mut()[0] = receiver.to_bits();
                    return;
                }
                {
                    let _profile =
                        crate::zfr_profile::scope(crate::zfr_profile::Category::ObjcImpCall);
                    match imp {
                        IMP::Host(host_imp) => {
                            // TODO: do type checks when calling GuestIMPs too.
                            // That requires using Objective-C type strings,
                            // rather than Rust types, and should probably
                            // warn rather than panicking,
                            // because apps might rely on type punning.
                            if let Some((sent_type_id, sent_type_desc)) = message_type_info {
                                let (expected_type_id, expected_type_desc) = host_imp.type_info();
                                if sent_type_id != expected_type_id {
                                    let msg = format!(
                                        "\
Type mismatch when sending message {} to {:?}!
- Message has type: {:?} / {}
- Method expects type: {:?} / {}",
                                        selector_name,
                                        receiver,
                                        sent_type_id,
                                        sent_type_desc,
                                        expected_type_id,
                                        expected_type_desc
                                    );
                                    if tolerate_type_mismatch {
                                        log!("Warning: {}", msg);
                                    } else {
                                        panic!("{}", msg);
                                    }
                                }
                            }
                            host_imp.call_from_guest(env)
                        }
                        // We can't create a new stack frame, because that would
                        // interfere with pass-through of stack arguments.
                        IMP::Guest(guest_imp) => guest_imp.call_without_pushing_stack_frame(env),
                    }
                }
                if let Some((call, start)) = zombie_farm_scroll_profile {
                    crate::zombie_farm_debug::finish_scroll_profile_call(
                        call,
                        start.elapsed(),
                        Some(env.cpu.regs()[0]),
                    );
                }
                if let Some(start) = zombie_farm_cell_build_profile {
                    crate::zombie_farm_debug::record_cell_build_message(
                        receiver_class_name,
                        selector_name,
                        start.elapsed(),
                    );
                }
                crate::zombie_farm_debug::end_cell_build_scope(
                    zombie_farm_cell_build_scope_started,
                );
                zombie_farm_finish_zombie_cell_assignment(
                    env,
                    zombie_farm_zombie_cell_assignment_started,
                    receiver,
                );
                if trace_zombie_farm_apply_scope {
                    ZOMBIE_FARM_APPLY_TRACE_DEPTH.fetch_sub(1, Ordering::Relaxed);
                }
                if trace_zombie_farm_layout {
                    trace_zombie_farm_layout_normal_return(env, receiver, selector);
                }
                if trace_zombie_farm_status {
                    trace_zombie_farm_status_normal_return(env, receiver, selector);
                    if zombie_farm_status_trace_enabled() {
                        let regs_before = *regs_before_zombie_farm_record
                            .as_ref()
                            .unwrap_or(&regs_before_zombie_farm_prepare);
                        match selector_name {
                            "latestStatus" | "status" | "getActivePlayer" | "notification" => {
                                zombie_farm_log_status_object_state(
                                    env,
                                    id::from_bits(env.cpu.regs()[0]),
                                    selector_name,
                                );
                            }
                            "setStatus:" | "setLatestStatus:" | "setActivePlayer:"
                            | "setCurrentPlayer:" | "setPlayerProfile:" | "setNotification:"
                            | "setNotifications:" | "setGameData:" | "setZfGameData:" => {
                                zombie_farm_log_status_object_state(
                                    env,
                                    id::from_bits(regs_before[2]),
                                    selector_name,
                                );
                            }
                            _ => {}
                        }
                    }
                }
                if trace_zombie_farm_quest {
                    trace_zombie_farm_quest_normal_return(env, receiver, selector);
                    let regs_before = *regs_before_zombie_farm_record
                        .as_ref()
                        .unwrap_or(&regs_before_zombie_farm_prepare);
                    match selector_name {
                        "setQuest:" => {
                            zombie_farm_log_quest_object_state(
                                env,
                                id::from_bits(regs_before[2]),
                                "ZFQuestCell setQuest:",
                            );
                        }
                        "quest" => {
                            zombie_farm_log_quest_object_state(
                                env,
                                id::from_bits(env.cpu.regs()[0]),
                                "ZFQuestCell quest",
                            );
                        }
                        "questPressed:" | "openMenuWithQuest:" => {
                            zombie_farm_log_quest_object_state(
                                env,
                                id::from_bits(regs_before[2]),
                                selector_name,
                            );
                        }
                        _ => {}
                    }
                }
                if record_zombie_farm_hunger {
                    crate::zombie_farm_debug::record_hunger_return(
                        env,
                        receiver,
                        receiver_class_name,
                        selector_name,
                    );
                }
                if record_zombie_farm_apply_trace {
                    crate::zombie_farm_debug::record_apply_trace_return(
                        env,
                        receiver,
                        receiver_class_name,
                        selector_name,
                    );
                }
                if record_zombie_farm_cocos_label_text {
                    crate::zombie_farm_debug::record_cocos_label_text_return(
                        env,
                        receiver,
                        receiver_class_name,
                        selector_name,
                        regs_before_zombie_farm_record.as_ref().unwrap(),
                    );
                }
                if zombie_farm_needs_post_dispatch_workarounds(env, selector_name_for_after) {
                    zombie_farm_post_dispatch_workarounds(env, receiver, selector_name_for_after);
                }
                return;
            } else {
                if using_cached_method_class {
                    env.objc
                        .remove_cached_method_class(orig_class, selector, super_lookup);
                    class = orig_class;
                    using_cached_method_class = false;
                    continue;
                }
                using_cached_method_class = false;
                class = superclass;
            }
        } else if let Some(&super::UnimplementedClass {
            ref name,
            is_metaclass,
        }) = host_object.as_any().downcast_ref()
        {
            panic!(
                "Class \"{}\" ({:?}) is unimplemented. Call to {} method \"{}\".",
                name,
                class,
                if is_metaclass { "class" } else { "instance" },
                selector.as_str(&env.mem),
            );
        } else if let Some(&super::FakeClass {
            ref name,
            is_metaclass,
        }) = host_object.as_any().downcast_ref()
        {
            log_dbg!(
                "Call to faked class \"{}\" ({:?}) {} method \"{}\". Behaving as if message was sent to nil.",
                name,
                class,
                if is_metaclass { "class" } else { "instance" },
                selector.as_str(&env.mem),
            );
            env.cpu.regs_mut()[0..2].fill(0);
            return;
        } else {
            panic!(
                "Item {class:?} in superclass chain of object {receiver:?}'s class {orig_class:?} has an unexpected host object type."
            );
        }
    }
}

/// Standard variant of `objc_msgSend`. See [objc_msgSend_inner].
#[allow(non_snake_case)]
pub(crate) fn objc_msgSend(env: &mut Environment, receiver: id, selector: SEL) {
    objc_msgSend_inner(
        env, receiver, selector, /* super2: */ None, /* tolerate_type_mismatch: */ false,
    )
}

#[allow(non_snake_case)]
pub(crate) fn _touchHLE_objc_msgSend_tolerant(env: &mut Environment, receiver: id, selector: SEL) {
    objc_msgSend_inner(
        env, receiver, selector, /* super2: */ None, /* tolerate_type_mismatch: */ true,
    )
}

/// Variant of `objc_msgSend` for methods that return a struct via a pointer.
/// See [objc_msgSend_inner].
///
/// The first parameter here is the pointer for the struct return. This is an
/// ABI detail that is usually hidden and handled behind-the-scenes by
/// [crate::abi], but `objc_msgSend` is a special case because of the
/// pass-through behaviour. Of course, the pass-through only works if the [IMP]
/// also has the pointer parameter. The caller therefore has to pick the
/// appropriate `objc_msgSend` variant depending on the method it wants to call.
pub(super) fn objc_msgSend_stret(
    env: &mut Environment,
    stret: MutVoidPtr,
    receiver: id,
    selector: SEL,
) {
    if zombie_farm_tag_summary_win_size_override(env, receiver, selector, stret) {
        return;
    }
    if zombie_farm_cell_content_size_override(env, receiver, selector, stret) {
        return;
    }
    objc_msgSend_inner(
        env, receiver, selector, /* super2: */ None, /* tolerate_type_mismatch: */ false,
    );
    trace_zombie_farm_layout_stret_return(env, receiver, selector, stret);
}

#[allow(non_snake_case)]
pub(crate) fn _touchHLE_objc_msgSend_stret_tolerant(
    env: &mut Environment,
    stret: MutVoidPtr,
    receiver: id,
    selector: SEL,
) {
    if zombie_farm_tag_summary_win_size_override(env, receiver, selector, stret) {
        return;
    }
    if zombie_farm_cell_content_size_override(env, receiver, selector, stret) {
        return;
    }
    objc_msgSend_inner(
        env, receiver, selector, /* super2: */ None, /* tolerate_type_mismatch: */ true,
    );
    trace_zombie_farm_layout_stret_return(env, receiver, selector, stret);
}

#[repr(C, packed)]
/// A pointer to this struct replaces the normal receiver parameter for
/// `objc_msgSendSuper2` and [msg_send_super2].
pub struct objc_super {
    pub receiver: id,
    /// If this is used with `objc_msgSendSuper` (not implemented here, TODO),
    /// this is a pointer to the superclass to look up the method on.
    /// If this is used with `objc_msgSendSuper2`, this is a pointer to a class
    /// and the superclass will be looked up from it.
    pub class: Class,
}
unsafe impl SafeRead for objc_super {}

/// Variant of `objc_msgSend` for supercalls. See [objc_msgSend_inner].
///
/// This variant has a weird ABI because it needs to receive an additional piece
/// of information (a class pointer), but it can't actually take this as an
/// extra parameter, because that would take one of the argument slots reserved
/// for arguments passed onto the method implementation. Hence the [objc_super]
/// pointer in place of the normal [id].
#[allow(non_snake_case)]
pub(super) fn objc_msgSendSuper2(
    env: &mut Environment,
    super_ptr: ConstPtr<objc_super>,
    selector: SEL,
) {
    let objc_super { receiver, class } = env.mem.read(super_ptr);

    // Rewrite first argument to match the normal ABI.
    crate::abi::write_next_arg(&mut 0, env.cpu.regs_mut(), &mut env.mem, receiver);

    objc_msgSend_inner(
        env,
        receiver,
        selector,
        /* super2: */ Some(class),
        /* tolerate_type_mismatch: */ false,
    )
}

/// Trait that assists with type-checking of [msg_send]'s arguments.
///
/// - Statically constrains the types of [msg_send]'s arguments so that the
///   first two are always [id] and [SEL].
/// - Provides the type ID to enable dynamic type checking of subsequent
///   arguments and the return type.
///
/// See `impl_HostIMP` for implementations. See also [MsgSendSuperSignature].
pub trait MsgSendSignature: 'static {
    /// Get the [TypeId] and a human-readable description for this signature.
    fn type_info() -> (TypeId, &'static str) {
        #[cfg(debug_assertions)]
        let type_name = std::any::type_name::<Self>();
        // Avoid wasting space on type names in release builds. At the time of
        // writing this saves about 36KB.
        #[cfg(not(debug_assertions))]
        let type_name = "[description unavailable in release builds]";
        (TypeId::of::<Self>(), type_name)
    }
}

/// Wrapper around [objc_msgSend] which, together with [msg], makes it easy to
/// send messages in host code. Warning: all types are inferred from the
/// call-site and they may not be checked, so be very sure you get them correct!
pub fn msg_send<R, P>(env: &mut Environment, args: P) -> R
where
    fn(&mut Environment, id, SEL): CallFromHost<R, P>,
    fn(&mut Environment, MutVoidPtr, id, SEL): CallFromHost<R, P>,
    (R, P): MsgSendSignature,
    R: GuestRet,
{
    // Provide type info for dynamic type checking.
    env.objc.message_type_info = Some(<(R, P) as MsgSendSignature>::type_info());
    if R::SIZE_IN_MEM.is_some() {
        (objc_msgSend_stret as fn(&mut Environment, MutVoidPtr, id, SEL)).call_from_host(env, args)
    } else {
        (objc_msgSend as fn(&mut Environment, id, SEL)).call_from_host(env, args)
    }
}

pub fn msg_send_no_type_checking<R, P>(env: &mut Environment, args: P) -> R
where
    fn(&mut Environment, id, SEL): CallFromHost<R, P>,
    fn(&mut Environment, MutVoidPtr, id, SEL): CallFromHost<R, P>,
    (R, P): MsgSendSignature,
    R: GuestRet,
{
    if R::SIZE_IN_MEM.is_some() {
        (_touchHLE_objc_msgSend_stret_tolerant as fn(&mut Environment, MutVoidPtr, id, SEL))
            .call_from_host(env, args)
    } else {
        (_touchHLE_objc_msgSend_tolerant as fn(&mut Environment, id, SEL)).call_from_host(env, args)
    }
}

/// Counterpart of [MsgSendSignature] for [msg_send_super2].
pub trait MsgSendSuperSignature: 'static {
    /// Signature with the [objc_super] pointer replaced by [id].
    type WithoutSuper: MsgSendSignature;
}

/// [msg_send] but for super-calls (calls [objc_msgSendSuper2]). You probably
/// want to use [msg_super] rather than calling this directly.
pub fn msg_send_super2<R, P>(env: &mut Environment, args: P) -> R
where
    fn(&mut Environment, ConstPtr<objc_super>, SEL): CallFromHost<R, P>,
    fn(&mut Environment, MutVoidPtr, ConstPtr<objc_super>, SEL): CallFromHost<R, P>,
    (R, P): MsgSendSuperSignature,
    R: GuestRet,
{
    // Provide type info for dynamic type checking.
    env.objc.message_type_info = Some(<(R, P) as MsgSendSuperSignature>::WithoutSuper::type_info());
    if R::SIZE_IN_MEM.is_some() {
        todo!() // no stret yet
    } else {
        (objc_msgSendSuper2 as fn(&mut Environment, ConstPtr<objc_super>, SEL))
            .call_from_host(env, args)
    }
}

/// Macro for sending a message which imitates the Objective-C messaging syntax.
/// See [msg_send] for the underlying implementation. Warning: all types are
/// inferred from the call-site and they may not be checked, so be very sure you
/// get them correct!
///
/// ```ignore
/// msg![env; foo setBar:bar withQux:qux];
/// ```
///
/// desugars to:
///
/// ```ignore
/// {
///     let sel = env.objc.lookup_selector("setFoo:withBar").unwrap();
///     msg_send(env, (foo, sel, bar, qux))
/// }
/// ```
///
/// Note that argument values that aren't a bare single identifier like `foo`
/// need to be bracketed.
///
/// See also [msg_class], if you want to send a message to a class.
#[macro_export]
macro_rules! msg {
    [$env:expr; $receiver:tt $name:ident $(: $arg1:tt $($($namen:ident)?: $argn:tt)*)?] => {
        {
            let sel = $crate::objc::selector!($($arg1;)? $name $($(, $($namen)?)*)?);
            let sel = $env.objc.lookup_selector(sel)
                .expect("Unknown selector");
            let args = ($receiver, sel, $($arg1, $($argn),*)?);
            $crate::objc::msg_send($env, args)
        }
    }
}
pub use crate::msg; // #[macro_export] is weird...

/// Variant of [msg] for super-calls.
///
/// Unlike the other variants, this macro can only be used within
/// [crate::objc::objc_classes], because it relies on that macro defining a
/// constant containing the name of the current class.
///
/// ```ignore
/// msg_super![env; this init]
/// ```
///
/// desugars to something like this, if the current class is `SomeClass`:
///
/// ```ignore
/// {
///     let super_arg_ptr = push_to_stack(env, objc_super {
///         receiver: this,
///         class: env.objc.get_known_class("SomeClass", &mut env.mem),
///     });
///     let sel = env.objc.lookup_selector("init").unwrap();
///     let res = msg_send_super2(env, (super_arg_ptr, sel));
///     pop_from_stack::<objc_super>(env);
///     res
/// }
/// ```
#[macro_export]
macro_rules! msg_super {
    [$env:expr; $receiver:tt $name:ident $(: $arg1:tt $($($namen:ident)?: $argn:tt)*)?] => {
        {
            let class = $env.objc.get_known_class(
                _OBJC_CURRENT_CLASS,
                &mut $env.mem
            );
            let sel = $crate::objc::selector!($($arg1;)? $name $($(, $($namen)?)*)?);
            let sel = $env.objc.lookup_selector(sel)
                .expect("Unknown selector");

            let sp = &mut $env.cpu.regs_mut()[$crate::cpu::Cpu::SP];
            let old_sp = *sp;
            *sp -= $crate::mem::guest_size_of::<$crate::objc::objc_super>();
            let super_ptr = $crate::mem::Ptr::from_bits(*sp);
            $env.mem.write(super_ptr, $crate::objc::objc_super {
                receiver: $receiver,
                class,
            });

            let args = (super_ptr.cast_const(), sel, $($arg1, $($argn),*)?);
            let res = $crate::objc::msg_send_super2($env, args);

            $env.cpu.regs_mut()[$crate::cpu::Cpu::SP] = old_sp;

            res
        }
    }
}
pub use crate::msg_super; // #[macro_export] is weird...

/// Variant of [msg] for sending a message to a named class. Useful for calling
/// class methods, especially `new`.
///
/// ```ignore
/// msg_class![env; SomeClass alloc]
/// ```
///
/// desugars to:
///
/// ```ignore
/// msg![env; (env.objc.get_known_class("SomeClass", &mut env.mem)) alloc]
/// ```
#[macro_export]
macro_rules! msg_class {
    [$env:expr; $receiver_class:ident $name:ident $(: $arg1:tt $($($namen:ident)?: $argn:tt)*)?] => {
        {
            let class = $env.objc.get_known_class(
                stringify!($receiver_class),
                &mut $env.mem
            );
            $crate::objc::msg![$env; class $name $(: $arg1 $($($namen)?: $argn)*)?]
        }
    }
}
pub use crate::msg_class; // #[macro_export] is weird...

/// Shorthand for `let _: id = msg![env; object retain];`
pub fn retain(env: &mut Environment, object: id) -> id {
    if object == nil {
        // fast path
        return nil;
    }
    msg![env; object retain]
}

/// Shorthand for `() = msg![env; object release];`
pub fn release(env: &mut Environment, object: id) {
    if object == nil {
        // fast path
        return;
    }
    msg![env; object release]
}

/// Shorthand for `let _: id = msg![env; object autorelease];`
pub fn autorelease(env: &mut Environment, object: id) -> id {
    if object == nil {
        // fast path
        return nil;
    }
    msg![env; object autorelease]
}
