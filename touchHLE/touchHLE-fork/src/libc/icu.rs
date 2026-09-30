/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Small shims for ICU symbols used by older apps.

use crate::dyld::{export_c_func, FunctionExports};
use crate::mem::{ConstPtr, GuestUSize, MutPtr, MutVoidPtr, Ptr};
use crate::Environment;

type UChar = u16;
type UBool = bool;
type UErrorCode = i32;
type URegularExpression = MutVoidPtr;

fn set_success(env: &mut Environment, status: MutPtr<UErrorCode>) {
    if !status.is_null() {
        env.mem.write(status, 0);
    }
}

fn uregex_open(
    env: &mut Environment,
    _pattern: ConstPtr<UChar>,
    _pattern_length: i32,
    _flags: u32,
    _parse_error: MutVoidPtr,
    status: MutPtr<UErrorCode>,
) -> URegularExpression {
    set_success(env, status);
    env.mem.alloc(1)
}

fn uregex_close(env: &mut Environment, regexp: URegularExpression) {
    if !regexp.is_null() {
        env.mem.free(regexp);
    }
}

fn uregex_setText(
    env: &mut Environment,
    _regexp: URegularExpression,
    _text: ConstPtr<UChar>,
    _text_length: i32,
    status: MutPtr<UErrorCode>,
) {
    set_success(env, status);
}

fn uregex_reset(
    env: &mut Environment,
    _regexp: URegularExpression,
    _index: i32,
    status: MutPtr<UErrorCode>,
) {
    set_success(env, status);
}

fn uregex_matches(
    env: &mut Environment,
    _regexp: URegularExpression,
    _start_index: i32,
    status: MutPtr<UErrorCode>,
) -> UBool {
    set_success(env, status);
    false
}

fn uregex_lookingAt(
    env: &mut Environment,
    _regexp: URegularExpression,
    _start_index: i32,
    status: MutPtr<UErrorCode>,
) -> UBool {
    set_success(env, status);
    false
}

fn uregex_find(
    env: &mut Environment,
    _regexp: URegularExpression,
    _start_index: i32,
    status: MutPtr<UErrorCode>,
) -> UBool {
    set_success(env, status);
    false
}

fn uregex_groupCount(
    env: &mut Environment,
    _regexp: URegularExpression,
    status: MutPtr<UErrorCode>,
) -> i32 {
    set_success(env, status);
    0
}

fn uregex_group(
    env: &mut Environment,
    _regexp: URegularExpression,
    _group_num: i32,
    _dest: MutPtr<UChar>,
    _dest_capacity: i32,
    status: MutPtr<UErrorCode>,
) -> i32 {
    set_success(env, status);
    0
}

fn uregex_start(
    env: &mut Environment,
    _regexp: URegularExpression,
    _group_num: i32,
    status: MutPtr<UErrorCode>,
) -> i32 {
    set_success(env, status);
    -1
}

fn uregex_end(
    env: &mut Environment,
    _regexp: URegularExpression,
    _group_num: i32,
    status: MutPtr<UErrorCode>,
) -> i32 {
    set_success(env, status);
    -1
}

fn u_strlen(env: &mut Environment, s: ConstPtr<UChar>) -> i32 {
    if s.is_null() {
        return 0;
    }
    let mut len: GuestUSize = 0;
    while env.mem.read(s + len) != 0 {
        len += 1;
    }
    len.try_into().unwrap()
}

fn u_strcmp(env: &mut Environment, a: ConstPtr<UChar>, b: ConstPtr<UChar>) -> i32 {
    let mut idx: GuestUSize = 0;
    loop {
        let ac = if a.is_null() {
            0
        } else {
            env.mem.read(a + idx)
        };
        let bc = if b.is_null() {
            0
        } else {
            env.mem.read(b + idx)
        };
        if ac != bc || ac == 0 {
            return i32::from(ac) - i32::from(bc);
        }
        idx += 1;
    }
}

fn u_strcpy(env: &mut Environment, dst: MutPtr<UChar>, src: ConstPtr<UChar>) -> MutPtr<UChar> {
    if dst.is_null() {
        return Ptr::null();
    }
    let mut idx: GuestUSize = 0;
    loop {
        let c = if src.is_null() {
            0
        } else {
            env.mem.read(src + idx)
        };
        env.mem.write(dst + idx, c);
        if c == 0 {
            return dst;
        }
        idx += 1;
    }
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(uregex_open(_, _, _, _, _)),
    export_c_func!(uregex_close(_)),
    export_c_func!(uregex_setText(_, _, _, _)),
    export_c_func!(uregex_reset(_, _, _)),
    export_c_func!(uregex_matches(_, _, _)),
    export_c_func!(uregex_lookingAt(_, _, _)),
    export_c_func!(uregex_find(_, _, _)),
    export_c_func!(uregex_groupCount(_, _)),
    export_c_func!(uregex_group(_, _, _, _, _)),
    export_c_func!(uregex_start(_, _, _)),
    export_c_func!(uregex_end(_, _, _)),
    export_c_func!(u_strlen(_)),
    export_c_func!(u_strcmp(_, _)),
    export_c_func!(u_strcpy(_, _)),
];
