/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Minimal libdispatch support.

use std::cell::Cell;
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};

use crate::abi::{CallFromHost, GuestFunction};
use crate::dyld::{export_c_func, FunctionExports};
use crate::mem::{ConstPtr, ConstVoidPtr, GuestUSize, MutPtr, MutVoidPtr, SafeRead};
use crate::Environment;

type DispatchOnceT = i32;
type DispatchQueueT = MutVoidPtr;
type DispatchTimeT = u64;

const DISPATCH_TIME_NOW: DispatchTimeT = 0;

const DISPATCH_ONCE_DONE: DispatchOnceT = -1;

static DISPATCH_SPECIFICS: LazyLock<Mutex<HashMap<(u32, u32), u32>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

thread_local! {
    static CURRENT_QUEUE: Cell<u32> = const { Cell::new(0) };
}

#[repr(C, packed)]
struct BlockLiteral {
    _isa: u32,
    _flags: i32,
    _reserved: i32,
    invoke: GuestFunction,
}
unsafe impl SafeRead for BlockLiteral {}

#[repr(C, packed)]
struct OpaqueDispatchQueue {
    _filler: u32,
}
unsafe impl SafeRead for OpaqueDispatchQueue {}

fn call_block(env: &mut Environment, block: ConstPtr<BlockLiteral>) {
    if block.is_null() {
        return;
    }

    let block_literal: BlockLiteral = env.mem.read(block);
    let invoke = block_literal.invoke;
    if invoke.addr_with_thumb_bit() != 0 {
        let block_ptr: ConstVoidPtr = block.cast();
        () = invoke.call_from_host(env, (block_ptr,));
    }
}

fn call_block_on_queue(
    env: &mut Environment,
    queue: DispatchQueueT,
    block: ConstPtr<BlockLiteral>,
) {
    CURRENT_QUEUE.with(|current_queue| {
        let previous_queue = current_queue.replace(queue.to_bits());
        call_block(env, block);
        current_queue.set(previous_queue);
    });
}

fn dispatch_once(
    env: &mut Environment,
    predicate: MutPtr<DispatchOnceT>,
    block: ConstPtr<BlockLiteral>,
) {
    if predicate.is_null() {
        return;
    }

    if env.mem.read(predicate) == DISPATCH_ONCE_DONE {
        return;
    }

    env.mem.write(predicate, DISPATCH_ONCE_DONE);

    call_block(env, block);
}

fn dispatch_once_f(
    env: &mut Environment,
    predicate: MutPtr<DispatchOnceT>,
    context: MutVoidPtr,
    function: GuestFunction,
) {
    if predicate.is_null() {
        return;
    }

    if env.mem.read(predicate) == DISPATCH_ONCE_DONE {
        return;
    }

    env.mem.write(predicate, DISPATCH_ONCE_DONE);

    if function.addr_with_thumb_bit() != 0 {
        () = function.call_from_host(env, (context,));
    }
}

fn dispatch_queue_create(
    env: &mut Environment,
    _label: ConstPtr<u8>,
    _attr: ConstVoidPtr,
) -> DispatchQueueT {
    env.mem
        .alloc_and_write(OpaqueDispatchQueue { _filler: 0 })
        .cast()
}

fn dispatch_get_main_queue(env: &mut Environment) -> DispatchQueueT {
    env.mem
        .alloc_and_write(OpaqueDispatchQueue { _filler: 0 })
        .cast()
}

fn dispatch_get_global_queue(
    env: &mut Environment,
    _identifier: i32,
    _flags: GuestUSize,
) -> DispatchQueueT {
    env.mem
        .alloc_and_write(OpaqueDispatchQueue { _filler: 0 })
        .cast()
}

fn dispatch_async(env: &mut Environment, _queue: DispatchQueueT, block: ConstPtr<BlockLiteral>) {
    call_block_on_queue(env, _queue, block);
}

fn dispatch_sync(env: &mut Environment, _queue: DispatchQueueT, block: ConstPtr<BlockLiteral>) {
    call_block_on_queue(env, _queue, block);
}

fn dispatch_after(
    env: &mut Environment,
    _when: DispatchTimeT,
    queue: DispatchQueueT,
    block: ConstPtr<BlockLiteral>,
) {
    call_block_on_queue(env, queue, block);
}

fn dispatch_time(_env: &mut Environment, _when: DispatchTimeT, delta: i64) -> DispatchTimeT {
    if delta <= 0 {
        DISPATCH_TIME_NOW
    } else {
        delta as DispatchTimeT
    }
}

fn dispatch_retain(_env: &mut Environment, object: DispatchQueueT) -> DispatchQueueT {
    object
}

fn dispatch_release(_env: &mut Environment, _object: DispatchQueueT) {}

fn dispatch_queue_set_specific(
    _env: &mut Environment,
    queue: DispatchQueueT,
    key: ConstVoidPtr,
    context: MutVoidPtr,
    _destructor: GuestFunction,
) {
    if key.is_null() {
        return;
    }

    DISPATCH_SPECIFICS
        .lock()
        .unwrap()
        .insert((queue.to_bits(), key.to_bits()), context.to_bits());
}

fn dispatch_queue_get_specific(
    _env: &mut Environment,
    queue: DispatchQueueT,
    key: ConstVoidPtr,
) -> MutVoidPtr {
    if key.is_null() {
        return MutVoidPtr::null();
    }

    DISPATCH_SPECIFICS
        .lock()
        .unwrap()
        .get(&(queue.to_bits(), key.to_bits()))
        .copied()
        .map(MutVoidPtr::from_bits)
        .unwrap_or_else(MutVoidPtr::null)
}

fn dispatch_get_specific(_env: &mut Environment, key: ConstVoidPtr) -> MutVoidPtr {
    if key.is_null() {
        return MutVoidPtr::null();
    }

    let current_queue = CURRENT_QUEUE.with(Cell::get);
    DISPATCH_SPECIFICS
        .lock()
        .unwrap()
        .get(&(current_queue, key.to_bits()))
        .copied()
        .map(MutVoidPtr::from_bits)
        .unwrap_or_else(MutVoidPtr::null)
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(dispatch_once(_, _)),
    export_c_func!(dispatch_once_f(_, _, _)),
    export_c_func!(dispatch_queue_create(_, _)),
    export_c_func!(dispatch_get_main_queue()),
    export_c_func!(dispatch_get_global_queue(_, _)),
    export_c_func!(dispatch_async(_, _)),
    export_c_func!(dispatch_sync(_, _)),
    export_c_func!(dispatch_after(_, _, _)),
    export_c_func!(dispatch_time(_, _)),
    export_c_func!(dispatch_retain(_)),
    export_c_func!(dispatch_release(_)),
    export_c_func!(dispatch_queue_set_specific(_, _, _, _)),
    export_c_func!(dispatch_queue_get_specific(_, _)),
    export_c_func!(dispatch_get_specific(_)),
];
