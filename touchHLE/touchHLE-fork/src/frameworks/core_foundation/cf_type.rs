/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CFType` (type-generic functions etc).

use super::{CFHashCode, CFIndex};
use crate::dyld::{export_c_func, export_c_func_aliased, FunctionExports};
use crate::objc::Class;
use crate::{msg, objc};
use crate::{msg_class, Environment};

pub type CFTypeRef = objc::id;

pub fn CFRetain(env: &mut Environment, object: CFTypeRef) -> CFTypeRef {
    assert!(!object.is_null()); // not allowed, unlike for normal objc objects
    objc::retain(env, object)
}
pub fn CFRelease(env: &mut Environment, object: CFTypeRef) {
    objc::release(env, object);
}

pub fn _CFMakeCollectable(_env: &mut Environment, object: CFTypeRef) -> CFTypeRef {
    // iPhone OS never had Objective-C garbage collection. Some older shared
    // code still links this symbol, but in a non-GC runtime it is just an
    // ownership annotation and must not change the object.
    object
}

pub fn CFGetRetainCount(env: &mut Environment, object: CFTypeRef) -> CFIndex {
    assert!(!object.is_null()); // not allowed, unlike for normal objc objects

    if let Some(count) = env.objc.try_get_refcount(object) {
        return count.get() as CFIndex;
    }

    if objc::ObjC::read_isa(object, &env.mem) == objc::nil {
        log!(
            "Warning: CFGetRetainCount({:?}) called on object with nil isa, returning 0",
            object
        );
        return 0;
    }

    msg![env; object retainCount]
}

pub fn CFEqual(env: &mut Environment, object1: CFTypeRef, object2: CFTypeRef) -> bool {
    if object1 == object2 {
        return true;
    }
    // TODO: other classes
    let str_class: Class = msg_class![env; NSString class];
    let object1_class: Class = msg![env; object1 class];
    assert!(msg![env; object1_class isKindOfClass:str_class]);
    let object2_class: Class = msg![env; object2 class];
    assert!(msg![env; object2_class isKindOfClass:str_class]);
    // TODO: use isEqual: once it is fixed
    msg![env; object1 isEqualToString:object2]
}

pub fn CFHash(env: &mut Environment, object: CFTypeRef) -> CFHashCode {
    msg![env; object hash]
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CFRetain(_)),
    export_c_func!(CFRelease(_)),
    export_c_func_aliased!("CFMakeCollectable", _CFMakeCollectable(_)),
    export_c_func!(CFGetRetainCount(_)),
    export_c_func!(CFEqual(_, _)),
    export_c_func!(CFHash(_)),
];
