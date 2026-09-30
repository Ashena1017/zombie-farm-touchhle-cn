/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Minimal `NSOperation` and `NSOperationQueue`.

use super::{ns_array, NSInteger, NSUInteger};
use crate::impl_HostObject_with_superclass;
use crate::mem::MutVoidPtr;
use crate::objc::{
    id, msg, nil, objc_classes, release, retain, ClassExports, HostObject, NSZonePtr, SEL,
};

#[derive(Default)]
struct NSOperationHostObject {
    cancelled: bool,
    finished: bool,
    queue_priority: NSInteger,
}
impl HostObject for NSOperationHostObject {}

struct NSInvocationOperationHostObject {
    superclass: NSOperationHostObject,
    target: id,
    selector: Option<SEL>,
    object: id,
}
impl_HostObject_with_superclass!(NSInvocationOperationHostObject);
impl Default for NSInvocationOperationHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            target: nil,
            selector: None,
            object: nil,
        }
    }
}

#[derive(Default)]
struct NSOperationQueueHostObject {
    suspended: bool,
    max_concurrent_operation_count: NSInteger,
    name: id,
}
impl HostObject for NSOperationQueueHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSOperation: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSOperationHostObject>::default(), &mut env.mem)
}

- (id)init {
    this
}

- (())dealloc {
    env.objc.dealloc_object(this, &mut env.mem)
}

- (())start {
    if !env.objc.borrow::<NSOperationHostObject>(this).cancelled {
        () = msg![env; this main];
    }
    env.objc.borrow_mut::<NSOperationHostObject>(this).finished = true;
}

- (())main {
}

- (())cancel {
    env.objc.borrow_mut::<NSOperationHostObject>(this).cancelled = true;
}

- (bool)isCancelled {
    env.objc.borrow::<NSOperationHostObject>(this).cancelled
}

- (bool)isFinished {
    env.objc.borrow::<NSOperationHostObject>(this).finished
}

- (bool)isExecuting {
    false
}

- (bool)isConcurrent {
    false
}

- (bool)isReady {
    true
}

- (())waitUntilFinished {
}

- (())addDependency:(id)_operation {
}

- (())removeDependency:(id)_operation {
}

- (id)dependencies {
    ns_array::from_vec(env, Vec::new())
}

- (NSInteger)queuePriority {
    env.objc.borrow::<NSOperationHostObject>(this).queue_priority
}

- (())setQueuePriority:(NSInteger)priority {
    env.objc.borrow_mut::<NSOperationHostObject>(this).queue_priority = priority;
}

@end

@implementation NSInvocationOperation: NSOperation

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSInvocationOperationHostObject>::default(), &mut env.mem)
}

- (id)initWithTarget:(id)target selector:(SEL)selector object:(id)object {
    retain(env, target);
    retain(env, object);
    let host = env.objc.borrow_mut::<NSInvocationOperationHostObject>(this);
    host.target = target;
    host.selector = Some(selector);
    host.object = object;
    this
}

- (())dealloc {
    let target = env.objc.borrow::<NSInvocationOperationHostObject>(this).target;
    let object = env.objc.borrow::<NSInvocationOperationHostObject>(this).object;
    release(env, target);
    release(env, object);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (())main {
    let host = env.objc.borrow::<NSInvocationOperationHostObject>(this);
    if host.target != nil {
        if let Some(selector) = host.selector {
            let target = host.target;
            let object = host.object;
            if selector.as_str(&env.mem).ends_with(':') {
                let _: id = msg![env; target performSelector:selector withObject:object];
            } else {
                let _: id = msg![env; target performSelector:selector];
            }
        }
    }
}

@end

@implementation NSBlockOperation: NSOperation

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSOperationHostObject>::default(), &mut env.mem)
}

+ (id)blockOperationWithBlock:(MutVoidPtr)_block {
    let operation: id = msg![env; this alloc];
    operation
}

- (())addExecutionBlock:(MutVoidPtr)_block {
}

@end

@implementation NSOperationQueue: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSOperationQueueHostObject>::default(), &mut env.mem)
}

+ (id)currentQueue {
    nil
}

+ (id)mainQueue {
    let queue: id = msg![env; this alloc];
    queue
}

- (id)init {
    env.objc.borrow_mut::<NSOperationQueueHostObject>(this).max_concurrent_operation_count = -1;
    this
}

- (())dealloc {
    let name = env.objc.borrow::<NSOperationQueueHostObject>(this).name;
    release(env, name);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (())addOperation:(id)operation {
    if operation != nil {
        () = msg![env; operation start];
    }
}

- (())addOperations:(id)operations waitUntilFinished:(bool)_wait {
    let count: NSUInteger = msg![env; operations count];
    for i in 0..count {
        let operation: id = msg![env; operations objectAtIndex:i];
        () = msg![env; this addOperation:operation];
    }
}

- (())addOperationWithBlock:(MutVoidPtr)_block {
}

- (())cancelAllOperations {
}

- (())waitUntilAllOperationsAreFinished {
}

- (id)operations {
    ns_array::from_vec(env, Vec::new())
}

- (NSUInteger)operationCount {
    0
}

- (bool)isSuspended {
    env.objc.borrow::<NSOperationQueueHostObject>(this).suspended
}

- (())setSuspended:(bool)suspended {
    env.objc.borrow_mut::<NSOperationQueueHostObject>(this).suspended = suspended;
}

- (NSInteger)maxConcurrentOperationCount {
    env.objc.borrow::<NSOperationQueueHostObject>(this).max_concurrent_operation_count
}

- (())setMaxConcurrentOperationCount:(NSInteger)count {
    env.objc.borrow_mut::<NSOperationQueueHostObject>(this).max_concurrent_operation_count = count;
}

- (id)name {
    env.objc.borrow::<NSOperationQueueHostObject>(this).name
}

- (())setName:(id)name {
    let old_name = env.objc.borrow::<NSOperationQueueHostObject>(this).name;
    retain(env, name);
    release(env, old_name);
    env.objc.borrow_mut::<NSOperationQueueHostObject>(this).name = name;
}

@end

};
