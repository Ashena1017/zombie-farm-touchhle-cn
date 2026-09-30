/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Small libgcc/compiler-rt helpers used by older ARM iOS binaries.

use crate::dyld::{export_c_func, ConstantExports, FunctionExports, HostConstant};
use crate::mem::ConstPtr;
use crate::Environment;

fn __divsi3(_env: &mut Environment, a: i32, b: i32) -> i32 {
    if b == 0 {
        0
    } else {
        a.wrapping_div(b)
    }
}

fn __modsi3(_env: &mut Environment, a: i32, b: i32) -> i32 {
    if b == 0 {
        0
    } else {
        a.wrapping_rem(b)
    }
}

fn __udivsi3(_env: &mut Environment, a: u32, b: u32) -> u32 {
    if b == 0 {
        0
    } else {
        a / b
    }
}

fn __umodsi3(_env: &mut Environment, a: u32, b: u32) -> u32 {
    if b == 0 {
        0
    } else {
        a % b
    }
}

fn __divdi3(_env: &mut Environment, a: i64, b: i64) -> i64 {
    if b == 0 {
        0
    } else {
        a.wrapping_div(b)
    }
}

fn __moddi3(_env: &mut Environment, a: i64, b: i64) -> i64 {
    if b == 0 {
        0
    } else {
        a.wrapping_rem(b)
    }
}

fn __udivdi3(_env: &mut Environment, a: u64, b: u64) -> u64 {
    if b == 0 {
        0
    } else {
        a / b
    }
}

fn __umoddi3(_env: &mut Environment, a: u64, b: u64) -> u64 {
    if b == 0 {
        0
    } else {
        a % b
    }
}

fn __fixdfdi(_env: &mut Environment, value: f64) -> i64 {
    value as i64
}

fn __floatdidf(_env: &mut Environment, value: i64) -> f64 {
    value as f64
}

fn __floatdisf(_env: &mut Environment, value: i64) -> f32 {
    value as f32
}

fn __floatundidf(_env: &mut Environment, value: u64) -> f64 {
    value as f64
}

fn __stack_chk_fail(_env: &mut Environment) {
    panic!("guest stack check failed");
}

fn __assert_rtn(
    env: &mut Environment,
    func: ConstPtr<u8>,
    file: ConstPtr<u8>,
    line: i32,
    expr: ConstPtr<u8>,
) {
    panic!(
        "guest assertion failed: {}:{}: {}: {}",
        env.mem.cstr_at_utf8(file).unwrap_or("<invalid file>"),
        line,
        env.mem.cstr_at_utf8(func).unwrap_or("<invalid func>"),
        env.mem.cstr_at_utf8(expr).unwrap_or("<invalid expr>"),
    );
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(__assert_rtn(_, _, _, _)),
    export_c_func!(__divdi3(_, _)),
    export_c_func!(__divsi3(_, _)),
    export_c_func!(__fixdfdi(_)),
    export_c_func!(__floatdidf(_)),
    export_c_func!(__floatdisf(_)),
    export_c_func!(__floatundidf(_)),
    export_c_func!(__moddi3(_, _)),
    export_c_func!(__modsi3(_, _)),
    export_c_func!(__stack_chk_fail()),
    export_c_func!(__udivdi3(_, _)),
    export_c_func!(__udivsi3(_, _)),
    export_c_func!(__umoddi3(_, _)),
    export_c_func!(__umodsi3(_, _)),
];

pub const CONSTANTS: ConstantExports = &[(
    "___stack_chk_guard",
    HostConstant::Custom(|env| {
        env.mem
            .alloc_and_write(0x5448_4c45u32)
            .cast_void()
            .cast_const()
    }),
)];
