/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSLock family`.
//!
//! TODO: There is probably an opportunity to refactor common methods.
//! (Need to find a good way to do so! Common super class wouldn't
//! work as it breaks expected inheritance chain.)

use crate::environment::MutexType::PTHREAD_MUTEX_RECURSIVE;
use crate::environment::{MutexId, PTHREAD_MUTEX_DEFAULT};
use crate::msg;
use crate::objc::{id, nil, objc_classes, ClassExports, HostObject};

struct NSLockHostObject {
    mutex_id: MutexId,
    name: id,
}
impl HostObject for NSLockHostObject {}

struct NSConditionLockHostObject {
    mutex_id: MutexId,
    condition: i32,
    name: id,
}
impl HostObject for NSConditionLockHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSLock: NSObject

+ (id)alloc {
    log_dbg!("[NSLock alloc]");
    let mutex_id = env.mutex_state.init_mutex(PTHREAD_MUTEX_DEFAULT);
    let host_object = NSLockHostObject { mutex_id, name: nil };
    env.objc.alloc_object(this, Box::new(host_object), &mut env.mem)
}

// NSLocking protocol implementation
- (())lock {
    log_dbg!("[(NSLock *){:?} lock]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    env.lock_mutex(host_object.mutex_id).unwrap();
}
- (())unlock {
    log_dbg!("[(NSLock *){:?} unlock]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    if !env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        echo!("*** -[NSLock unlock]: lock (<NSLock: {:?}> '{:?}') unlocked when not locked", this, host_object.name);
    }
    env.unlock_mutex(host_object.mutex_id).unwrap();
}

- (bool)tryLock {
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    if env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        false
    } else {
        env.lock_mutex(host_object.mutex_id).is_ok()
    }
}

- (())setName:(id)name { // NSString *
    // @property(copy), name has to be copied
    env.objc.borrow_mut::<NSLockHostObject>(this).name = msg![env; name copy];
}
- (id)name {
    env.objc.borrow::<NSLockHostObject>(this).name
}

- (())dealloc {
    log_dbg!("[(NSLock *){:?} dealloc]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    env.mutex_state.destroy_mutex(host_object.mutex_id).unwrap();
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

@implementation NSConditionLock: NSObject

+ (id)alloc {
    let mutex_id = env.mutex_state.init_mutex(PTHREAD_MUTEX_RECURSIVE);
    let host_object = NSConditionLockHostObject {
        mutex_id,
        condition: 0,
        name: nil,
    };
    env.objc.alloc_object(this, Box::new(host_object), &mut env.mem)
}

- (id)initWithCondition:(i32)condition {
    env.objc.borrow_mut::<NSConditionLockHostObject>(this).condition = condition;
    this
}

- (i32)condition {
    env.objc.borrow::<NSConditionLockHostObject>(this).condition
}

- (())lock {
    let host_object = env.objc.borrow::<NSConditionLockHostObject>(this);
    env.lock_mutex(host_object.mutex_id).unwrap();
}

- (bool)tryLock {
    let host_object = env.objc.borrow::<NSConditionLockHostObject>(this);
    if env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        false
    } else {
        env.lock_mutex(host_object.mutex_id).is_ok()
    }
}

- (())unlock {
    let host_object = env.objc.borrow::<NSConditionLockHostObject>(this);
    if !env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        echo!("*** -[NSConditionLock unlock]: lock (<NSConditionLock: {:?}> '{:?}') unlocked when not locked", this, host_object.name);
    }
    env.unlock_mutex(host_object.mutex_id).unwrap();
}

- (())unlockWithCondition:(i32)condition {
    env.objc.borrow_mut::<NSConditionLockHostObject>(this).condition = condition;
    let _: () = msg![env; this unlock];
}

- (())lockWhenCondition:(i32)condition {
    // touchHLE is effectively cooperative here; don't block forever waiting
    // for network helper conditions that are only used to serialize callbacks.
    let _: () = msg![env; this lock];
    env.objc.borrow_mut::<NSConditionLockHostObject>(this).condition = condition;
}

- (bool)tryLockWhenCondition:(i32)condition {
    let ok: bool = msg![env; this tryLock];
    if ok {
        env.objc.borrow_mut::<NSConditionLockHostObject>(this).condition = condition;
    }
    ok
}

- (bool)lockBeforeDate:(id)_limit {
    let _: () = msg![env; this lock];
    true
}

- (bool)lockWhenCondition:(i32)condition beforeDate:(id)_limit {
    let _: () = msg![env; this lockWhenCondition:condition];
    true
}

- (())setName:(id)name {
    env.objc.borrow_mut::<NSConditionLockHostObject>(this).name = msg![env; name copy];
}

- (id)name {
    env.objc.borrow::<NSConditionLockHostObject>(this).name
}

- (())dealloc {
    let host_object = env.objc.borrow::<NSConditionLockHostObject>(this);
    env.mutex_state.destroy_mutex(host_object.mutex_id).unwrap();
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

@implementation NSRecursiveLock: NSObject

+ (id)alloc {
    log_dbg!("[NSRecursiveLock alloc]");
    let mutex_id = env.mutex_state.init_mutex(PTHREAD_MUTEX_RECURSIVE);
    let host_object = NSLockHostObject { mutex_id, name: nil };
    env.objc.alloc_object(this, Box::new(host_object), &mut env.mem)
}

// NSLocking protocol implementation
- (())lock {
    log_dbg!("[(NSRecursiveLock *){:?} lock]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    env.lock_mutex(host_object.mutex_id).unwrap();
}
- (())unlock {
    log_dbg!("[(NSRecursiveLock *){:?} unlock]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    if !env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        echo!("*** -[NSRecursiveLock unlock]: lock (<NSRecursiveLock: {:?}> '{:?}') unlocked when not locked", this, host_object.name);
    }
    env.unlock_mutex(host_object.mutex_id).unwrap();
}

- (bool)tryLock {
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    if env.mutex_state.mutex_is_locked(host_object.mutex_id) {
        false
    } else {
        env.lock_mutex(host_object.mutex_id).is_ok()
    }
}

- (())setName:(id)name { // NSString *
    // @property(copy), name has to be copied
    env.objc.borrow_mut::<NSLockHostObject>(this).name = msg![env; name copy];
}
- (id)name {
    env.objc.borrow::<NSLockHostObject>(this).name
}

- (())dealloc {
    log_dbg!("[(NSRecursiveLock *){:?} dealloc]", this);
    let host_object = env.objc.borrow::<NSLockHostObject>(this);
    env.mutex_state.destroy_mutex(host_object.mutex_id).unwrap();
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};
