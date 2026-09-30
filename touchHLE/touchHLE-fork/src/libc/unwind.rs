/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! ARM SJLJ unwinding entry points.
//!
//! Older iPhone OS binaries built with GCC/LLVM's setjmp/longjmp exception
//! model call these functions to register stack-local exception contexts.
//! touchHLE does not currently implement C++/Objective-C exception unwinding,
//! but registration itself has no visible effect unless an exception is thrown.

#![allow(non_snake_case)]

use crate::dyld::{export_c_func, FunctionExports};
use crate::mem::MutVoidPtr;
use crate::Environment;

fn _Unwind_SjLj_Register(_env: &mut Environment, fc: MutVoidPtr) {
    log_dbg!("Ignoring _Unwind_SjLj_Register({:?})", fc);
}

fn _Unwind_SjLj_Unregister(_env: &mut Environment, fc: MutVoidPtr) {
    log_dbg!("Ignoring _Unwind_SjLj_Unregister({:?})", fc);
}

fn _Unwind_SjLj_Resume(_env: &mut Environment, exception_object: MutVoidPtr) {
    panic!(
        "_Unwind_SjLj_Resume({:?}) called, but exception unwinding is not implemented",
        exception_object
    );
}

fn _Unwind_SjLj_Resume_or_Rethrow(_env: &mut Environment, exception_object: MutVoidPtr) {
    panic!(
        "_Unwind_SjLj_Resume_or_Rethrow({:?}) called, but exception unwinding is not implemented",
        exception_object
    );
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(_Unwind_SjLj_Register(_)),
    export_c_func!(_Unwind_SjLj_Unregister(_)),
    export_c_func!(_Unwind_SjLj_Resume(_)),
    export_c_func!(_Unwind_SjLj_Resume_or_Rethrow(_)),
];
