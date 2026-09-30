/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Minimal `CFUUID`.

use super::cf_allocator::{kCFAllocatorDefault, CFAllocatorRef};
use super::cf_string::CFStringRef;
use super::CFTypeRef;
use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::foundation::ns_string::from_rust_string;
use crate::objc::msg;
use crate::Environment;

type CFUUIDRef = CFTypeRef;

fn CFUUIDCreate(env: &mut Environment, allocator: CFAllocatorRef) -> CFUUIDRef {
    assert!(allocator == kCFAllocatorDefault || env.mem.read(allocator).is_system_default()); // unimplemented
    from_rust_string(env, "00000000-0000-4000-8000-000000000000".to_string())
}

fn CFUUIDCreateString(
    env: &mut Environment,
    allocator: CFAllocatorRef,
    uuid: CFUUIDRef,
) -> CFStringRef {
    assert!(allocator == kCFAllocatorDefault || env.mem.read(allocator).is_system_default()); // unimplemented
    if uuid.is_null() {
        CFUUIDCreate(env, allocator)
    } else {
        msg![env; uuid copy]
    }
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CFUUIDCreate(_)),
    export_c_func!(CFUUIDCreateString(_, _)),
];
