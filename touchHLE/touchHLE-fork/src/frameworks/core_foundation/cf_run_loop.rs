/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CFRunLoop`.
//!
//! This is not even toll-free bridged to `NSRunLoop` in Apple's implementation,
//! but here it is the same type.

use crate::dyld::{export_c_func, ConstantExports, FunctionExports, HostConstant};
use crate::frameworks::core_foundation::time::CFTimeInterval;
use crate::frameworks::foundation::ns_run_loop::{
    run_run_loop_single_iteration, run_run_loop_single_iteration_non_blocking,
};
use crate::frameworks::foundation::ns_string;
use crate::objc::{id, msg, msg_class};
use crate::Environment;

pub type CFRunLoopRef = super::CFTypeRef;
pub type CFRunLoopMode = super::cf_string::CFStringRef;

fn CFRunLoopGetCurrent(env: &mut Environment) -> CFRunLoopRef {
    msg_class![env; NSRunLoop currentRunLoop]
}

pub fn CFRunLoopGetMain(env: &mut Environment) -> CFRunLoopRef {
    msg_class![env; NSRunLoop mainRunLoop]
}

fn CFRunLoopRunInMode(
    env: &mut Environment,
    mode: CFRunLoopMode,
    seconds: CFTimeInterval,
    _return_something: bool,
) -> i32 {
    let default_mode = ns_string::get_static_str(env, kCFRunLoopDefaultMode);
    let common_modes = ns_string::get_static_str(env, kCFRunLoopCommonModes);
    // TODO: handle other modes
    assert!(
        msg![env; mode isEqualToString:default_mode]
            || msg![env; mode isEqualToString:common_modes]
    );
    let current_run_loop = CFRunLoopGetCurrent(env);
    if seconds == 0.0 {
        // A zero timeout means "do not block": process what is ready now and
        // return immediately. Apps that poll this every frame (e.g. cocos2d's
        // `CCFastDirector`, used by Zombie Farm, which calls it twice per
        // frame) depend on that, and otherwise end up paced at half their
        // intended framerate.
        //
        // Opt-in, because making it the default would change the pacing of
        // every app; apps that rely on the run loop itself for pacing would
        // start spinning instead.
        if env.options.non_blocking_zero_timeout_run_loop {
            run_run_loop_single_iteration_non_blocking(env, current_run_loop);
        } else {
            run_run_loop_single_iteration(env, current_run_loop);
        }
    } else {
        let limit_date: id = msg_class![env; NSDate dateWithTimeIntervalSinceNow:seconds];
        () = msg![env; current_run_loop runUntilDate:limit_date];
    }
    1 // kCFRunLoopRunFinished
}

pub const kCFRunLoopCommonModes: &str = "kCFRunLoopCommonModes";
pub const kCFRunLoopDefaultMode: &str = "kCFRunLoopDefaultMode";

pub const CONSTANTS: ConstantExports = &[
    (
        "_kCFRunLoopCommonModes",
        HostConstant::NSString(kCFRunLoopCommonModes),
    ),
    (
        "_kCFRunLoopDefaultMode",
        HostConstant::NSString(kCFRunLoopDefaultMode),
    ),
];

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CFRunLoopGetCurrent()),
    export_c_func!(CFRunLoopGetMain()),
    export_c_func!(CFRunLoopRunInMode(_, _, _)),
];
