/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSInvocation`.

use crate::abi::{extend_stack_for_args, write_next_arg, GuestArg};
use crate::cpu::Cpu;
use crate::frameworks::foundation::{NSInteger, NSUInteger};
use crate::libc::string::strdup;
use crate::mem::{ConstPtr, MutPtr, MutVoidPtr};
use crate::msg;
use crate::objc::{
    autorelease, id, nil, objc_classes, objc_msgSend, release, retain, ClassExports, HostObject,
    ObjC, SEL,
};

struct NSInvocationHostObject {
    /// `NSMethodSignature *`
    sig: id,
    /// Argument type strings resolved from `sig` at creation time
    argument_types: Vec<String>,
    target: id,
    selector: Option<SEL>,
    /// Per-slot owned buffer for each argument.
    /// Option denotes if argument was set with `setArgument:atIndex:`
    arguments: Vec<Option<MutVoidPtr>>,
    arguments_retained: bool,
    /// Objects retained by `retainArguments`
    retained_objects: Vec<id>,
    /// C string copies made by `retainArguments`
    copied_strings: Vec<MutPtr<u8>>,
    /// Owned buffer for the last return value, if non-void.
    return_value: Option<MutVoidPtr>,
}
impl HostObject for NSInvocationHostObject {}

pub struct DebugInvocationInfo {
    pub target: id,
    pub selector_name: Option<String>,
    pub arguments: Vec<DebugInvocationArgument>,
}

pub struct DebugInvocationArgument {
    pub index: usize,
    pub type_: String,
    pub value: Option<DebugInvocationArgumentValue>,
}

pub enum DebugInvocationArgumentValue {
    Object(id),
    Selector(SEL),
    F32(f32),
    F64(f64),
    I32(i32),
    U32(u32),
    I64(i64),
    U64(u64),
    Pointer(u32),
}

pub fn debug_invocation_info(
    env: &crate::Environment,
    invocation: id,
) -> Option<DebugInvocationInfo> {
    let host = env.objc.borrow::<NSInvocationHostObject>(invocation);
    let selector_name = host
        .selector
        .map(|selector| selector.as_str(&env.mem).to_string());
    let mut arguments = Vec::new();
    for (index, type_) in host.argument_types.iter().enumerate().skip(2) {
        let value = host.arguments.get(index).and_then(|argument| {
            let argument = (*argument)?;
            Some(match type_.as_str() {
                "@" => DebugInvocationArgumentValue::Object(env.mem.read(argument.cast())),
                ":" => DebugInvocationArgumentValue::Selector(env.mem.read(argument.cast())),
                "f" => DebugInvocationArgumentValue::F32(env.mem.read(argument.cast())),
                "d" => DebugInvocationArgumentValue::F64(env.mem.read(argument.cast())),
                "c" | "B" => {
                    let value: u8 = env.mem.read(argument.cast());
                    DebugInvocationArgumentValue::U32(value as u32)
                }
                "s" => {
                    let value: i16 = env.mem.read(argument.cast());
                    DebugInvocationArgumentValue::I32(value as i32)
                }
                "S" => {
                    let value: u16 = env.mem.read(argument.cast());
                    DebugInvocationArgumentValue::U32(value as u32)
                }
                "i" | "l" => DebugInvocationArgumentValue::I32(env.mem.read(argument.cast())),
                "I" | "L" => DebugInvocationArgumentValue::U32(env.mem.read(argument.cast())),
                "q" => DebugInvocationArgumentValue::I64(env.mem.read(argument.cast())),
                "Q" => DebugInvocationArgumentValue::U64(env.mem.read(argument.cast())),
                "*" => {
                    let ptr: MutPtr<u8> = env.mem.read(argument.cast());
                    DebugInvocationArgumentValue::Pointer(ptr.to_bits())
                }
                _ if type_.starts_with('^') => {
                    let ptr: MutVoidPtr = env.mem.read(argument.cast());
                    DebugInvocationArgumentValue::Pointer(ptr.to_bits())
                }
                _ => DebugInvocationArgumentValue::Pointer(argument.to_bits()),
            })
        });
        arguments.push(DebugInvocationArgument {
            index,
            type_: type_.clone(),
            value,
        });
    }

    Some(DebugInvocationInfo {
        target: host.target,
        selector_name,
        arguments,
    })
}

fn scalar_size_for_type(type_: &str) -> Option<usize> {
    Some(match type_ {
        "c" | "B" => 1,
        "s" | "S" => 2,
        "i" | "I" | "l" | "L" | "f" | "@" | ":" | "*" => 4,
        "q" | "Q" | "d" => 8,
        _ if type_.starts_with('^') => 4,
        _ => return None,
    })
}

fn store_return_value(env: &mut crate::Environment, this: id, ret_type: &str) {
    if ret_type == "v" {
        if let Some(ptr) = env
            .objc
            .borrow_mut::<NSInvocationHostObject>(this)
            .return_value
            .take()
        {
            env.mem.free(ptr.cast());
        }
        return;
    }

    let old = env
        .objc
        .borrow_mut::<NSInvocationHostObject>(this)
        .return_value
        .take();
    if let Some(ptr) = old {
        env.mem.free(ptr.cast());
    }

    let new_value: MutVoidPtr = match ret_type {
        "@" => {
            let value = env.cpu.regs()[0];
            env.mem.alloc_and_write(id::from_bits(value)).cast()
        }
        ":" => {
            let value = <SEL as crate::abi::GuestRet>::from_regs(env.cpu.regs());
            env.mem.alloc_and_write(value).cast()
        }
        "f" => {
            let value = <f32 as crate::abi::GuestRet>::from_regs(env.cpu.regs());
            env.mem.alloc_and_write(value).cast()
        }
        "d" => {
            let value = <f64 as crate::abi::GuestRet>::from_regs(env.cpu.regs());
            env.mem.alloc_and_write(value).cast()
        }
        "c" | "B" => {
            let value = env.cpu.regs()[0] as u8;
            env.mem.alloc_and_write(value).cast()
        }
        "s" => {
            let value = env.cpu.regs()[0] as i16;
            env.mem.alloc_and_write(value).cast()
        }
        "S" => {
            let value = env.cpu.regs()[0] as u16;
            env.mem.alloc_and_write(value).cast()
        }
        "i" | "l" => {
            let value = env.cpu.regs()[0] as i32;
            env.mem.alloc_and_write(value).cast()
        }
        "I" | "L" => {
            let value = env.cpu.regs()[0];
            env.mem.alloc_and_write(value).cast()
        }
        "q" => {
            let value = <i64 as crate::abi::GuestRet>::from_regs(env.cpu.regs());
            env.mem.alloc_and_write(value).cast()
        }
        "Q" => {
            let value = <u64 as crate::abi::GuestRet>::from_regs(env.cpu.regs());
            env.mem.alloc_and_write(value).cast()
        }
        "*" => {
            let value = MutPtr::<u8>::from_bits(env.cpu.regs()[0]);
            env.mem.alloc_and_write(value).cast()
        }
        _ if ret_type.starts_with('^') => {
            let value = MutVoidPtr::from_bits(env.cpu.regs()[0]);
            env.mem.alloc_and_write(value).cast()
        }
        _ => unimplemented!("NSInvocation return type {ret_type}"),
    };

    env.objc
        .borrow_mut::<NSInvocationHostObject>(this)
        .return_value = Some(new_value);
}

fn should_skip_zombie_farm_unset_invocation(env: &mut crate::Environment, invocation: id) -> bool {
    let host = env.objc.borrow::<NSInvocationHostObject>(invocation);
    let target = host.target;
    let selector_name = host
        .selector
        .map(|selector| selector.as_str(&env.mem).to_string());
    let missing_cancel_notification = host.arguments.get(4).is_some_and(Option::is_none)
        && host
            .argument_types
            .get(4)
            .is_some_and(|arg_type| arg_type == "@");

    let target_class = ObjC::read_isa(target, &env.mem);
    let target_class_name = env.objc.try_get_class_name(target_class).unwrap_or("");
    env.bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        && target_class_name == "StatusBar"
        && selector_name.as_deref() == Some("updateMessage:andCancelTimeout:andCancelNotification:")
        && missing_cancel_notification
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSInvocation: NSObject

+ (id)invocationWithMethodSignature:(id)sig { // NSMethodSignature *
    retain(env, sig);
    let num_of_args: NSUInteger = msg![env; sig numberOfArguments];
    let mut argument_types: Vec<String> = Vec::with_capacity(num_of_args as usize);
    for i in 0..num_of_args {
        let type_ptr: ConstPtr<u8> = msg![env; sig getArgumentTypeAtIndex:i];
        argument_types.push(env.mem.cstr_at_utf8(type_ptr).unwrap().to_string());
    }
    let host_object = Box::new(NSInvocationHostObject {
        sig,
        argument_types,
        target: nil,
        selector: None,
        arguments: vec![None; num_of_args as usize],
        arguments_retained: false,
        retained_objects: Vec::new(),
        copied_strings: Vec::new(),
        return_value: None,
    });
    let res = env.objc.alloc_object(this, host_object, &mut env.mem);
    autorelease(env, res)
}

- (())setTarget:(id)target {
    let old_target = env.objc.borrow::<NSInvocationHostObject>(this).target;
    let arguments_retained = env.objc.borrow::<NSInvocationHostObject>(this).arguments_retained;
    env.objc.borrow_mut::<NSInvocationHostObject>(this).target = target;
    if arguments_retained {
        retain(env, target);
        release(env, old_target);
    }
}

- (())setSelector:(SEL)selector {
    assert!(env.objc.borrow_mut::<NSInvocationHostObject>(this).selector.is_none()); // TODO
    env.objc.borrow_mut::<NSInvocationHostObject>(this).selector = Some(selector);
}

- (())retainArguments {
    // TODO: handle return val
    // TODO: copy blocks
    assert!(!env.objc.borrow::<NSInvocationHostObject>(this).arguments_retained); // TODO

    let target = env.objc.borrow::<NSInvocationHostObject>(this).target;
    retain(env, target);

    let mut retained_objects: Vec<id> = Vec::new();
    let mut copied_strings: Vec<MutPtr<u8>> = Vec::new();

    // Skip index 0 (self) and 1 (SEL): handled via target/selector fields.
    let num_of_args = env.objc.borrow::<NSInvocationHostObject>(this).argument_types.len();
    for i in 2..num_of_args {
        let host = env.objc.borrow::<NSInvocationHostObject>(this);
        let Some(arg_loc) = host.arguments[i] else { continue };
        match host.argument_types[i].as_str() {
            "@" => {
                let obj: id = env.mem.read(arg_loc.cast().cast_const());
                retain(env, obj);
                retained_objects.push(obj);
            }
            "*" => {
                let str: MutPtr<u8> = env.mem.read(arg_loc.cast().cast_const());
                let str_copy = strdup(env, str.cast_const());
                env.mem.write(arg_loc.cast(), str_copy);
                copied_strings.push(str_copy);
            }
            _ => {}
        }
    }

    let host = env.objc.borrow_mut::<NSInvocationHostObject>(this);
    host.retained_objects = retained_objects;
    host.copied_strings = copied_strings;
    host.arguments_retained = true;
}

- (())setArgument:(MutVoidPtr)arg_loc
          atIndex:(NSInteger)idx {
    let &NSInvocationHostObject {
        ref arguments,
        arguments_retained,
        ..
    } = env.objc.borrow::<NSInvocationHostObject>(this);

    // 0 and 1 are reserved for `self` and `_cmd`
    // TODO: can they be set too?
    assert!(1 < idx && idx < arguments.len() as NSInteger);

    if let Some(prev_arg) = arguments[idx as usize] {
        env.mem.free(prev_arg.cast());
    }

    let argument_types: &Vec<String> = env.objc.borrow::<NSInvocationHostObject>(this).argument_types.as_ref();
    let arg_type = argument_types.get(idx as usize).unwrap();
    let new: MutVoidPtr = match arg_type.as_str() {
        "f" => {
            let arg_loc: MutPtr<f32> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "d" => {
            let arg_loc: MutPtr<f64> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "c" | "B" => {
            let arg_loc: MutPtr<u8> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "s" => {
            let arg_loc: MutPtr<i16> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "S" => {
            let arg_loc: MutPtr<u16> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "i" | "l" => {
            let arg_loc: MutPtr<i32> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "I" | "L" => {
            let arg_loc: MutPtr<u32> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "q" => {
            let arg_loc: MutPtr<i64> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "Q" => {
            let arg_loc: MutPtr<u64> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "@" => {
            assert!(!arguments_retained); // TODO
            let arg_loc: MutPtr<id> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        "*" => {
            assert!(!arguments_retained); // TODO
            let arg_loc: MutPtr<MutPtr<u8>> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        // pointer cases
        _ if arg_type.starts_with('^') => {
            let arg_loc: MutPtr<MutVoidPtr> = arg_loc.cast();
            let arg = env.mem.read(arg_loc);
            env.mem.alloc_and_write(arg).cast()
        }
        _ => unimplemented!("unhandled argument type {arg_type}"),
    };

    env.objc.borrow_mut::<NSInvocationHostObject>(this).arguments[idx as usize] = Some(new);
}

- (())invokeWithTarget:(id)target {
    () = msg![env; this setTarget:target];
    () = msg![env; this invoke];
}

- (())invoke {
    let sig = env.objc.borrow::<NSInvocationHostObject>(this).sig;
    let ret_type: ConstPtr<u8> = msg![env; sig methodReturnType];
    let ret_type = env.mem.cstr_at_utf8(ret_type).unwrap().to_string();

    let &NSInvocationHostObject { target, selector, .. } = env.objc.borrow::<NSInvocationHostObject>(this);
    if target == nil {
        log_dbg!(
            "Ignoring NSInvocation {:?} with nil target for selector {:?}",
            this,
            selector.map(|sel| sel.as_str(&env.mem).to_string()),
        );
        return;
    }
    if should_skip_zombie_farm_unset_invocation(env, this) {
        log_dbg!("ZombieFarm: skipping incomplete StatusBar notification invocation");
        return;
    }

    // `call_from_host` re-use
    // TODO: retval_ptr
    // TODO: cross check against frame length from NSMethodSignature
    let mut reg_count = 0;
    let argument_types = env
        .objc
        .borrow::<NSInvocationHostObject>(this)
        .argument_types
        .clone();
    for arg_type in argument_types.iter() {
        // TODO: refactor and simplify
        reg_count += match arg_type.as_str() {
            "@" => <id as GuestArg>::REG_COUNT,
            ":" => <SEL as GuestArg>::REG_COUNT,
            "f" => <f32 as GuestArg>::REG_COUNT,
            "d" => <f64 as GuestArg>::REG_COUNT,
            "c" | "B" => <u8 as GuestArg>::REG_COUNT,
            "s" => <i16 as GuestArg>::REG_COUNT,
            "S" => <u16 as GuestArg>::REG_COUNT,
            "i" | "l" => <i32 as GuestArg>::REG_COUNT,
            "I" | "L" => <u32 as GuestArg>::REG_COUNT,
            "q" => <i64 as GuestArg>::REG_COUNT,
            "Q" => <u64 as GuestArg>::REG_COUNT,
            "*" => <MutPtr<u8> as GuestArg>::REG_COUNT,
            // pointer cases
            _ if arg_type.starts_with('^') => <MutVoidPtr as GuestArg>::REG_COUNT,
            _ => unimplemented!("reg_count for {arg_type}")
        }
    }
    let regs = env.cpu.regs_mut();
    let old_sp = extend_stack_for_args(
        reg_count,
        regs,
    );

    let arguments = env
        .objc
        .borrow::<NSInvocationHostObject>(this)
        .arguments
        .clone();
    let mut reg_offset = 0;
    for i in 0..arguments.len() {
        // TODO: do not handle target and sel as special cases
        if i == 0 {
            assert!(argument_types[i] == "@");
            // target
            let target = env.objc.borrow::<NSInvocationHostObject>(this).target;
            let regs = env.cpu.regs_mut();
            write_next_arg::<id>(&mut reg_offset, regs, &mut env.mem, target);
            continue;
        }
        if i == 1 {
            assert!(argument_types[i] == ":");
            // selector
            let selector = env.objc.borrow::<NSInvocationHostObject>(this).selector.unwrap();
            let regs = env.cpu.regs_mut();
            write_next_arg::<SEL>(&mut reg_offset, regs, &mut env.mem, selector);
            continue;
        }
        let arg_type = argument_types[i].as_str();
        let Some(arg_slot) = arguments[i] else {
            let target = env.objc.borrow::<NSInvocationHostObject>(this).target;
            let selector = env.objc.borrow::<NSInvocationHostObject>(this).selector;
            let target_class = crate::objc::ObjC::read_isa(target, &env.mem);
            let target_class_name = env
                .objc
                .try_get_class_name(target_class)
                .unwrap_or("<unknown>");
            log!(
                "Warning: invoking NSInvocation {:?} target {:?} ({}) selector {:?} with unset argument {} of type {}",
                this,
                target,
                target_class_name,
                selector.map(|sel| sel.as_str(&env.mem).to_string()),
                i,
                arg_type
            );
            let regs = env.cpu.regs_mut();
            match arg_type {
                "@" => write_next_arg::<id>(&mut reg_offset, regs, &mut env.mem, nil),
                "f" => write_next_arg::<f32>(&mut reg_offset, regs, &mut env.mem, 0.0),
                "d" => write_next_arg::<f64>(&mut reg_offset, regs, &mut env.mem, 0.0),
                "c" | "B" => write_next_arg::<u8>(&mut reg_offset, regs, &mut env.mem, 0),
                "s" => write_next_arg::<i16>(&mut reg_offset, regs, &mut env.mem, 0),
                "S" => write_next_arg::<u16>(&mut reg_offset, regs, &mut env.mem, 0),
                "i" | "l" => write_next_arg::<i32>(&mut reg_offset, regs, &mut env.mem, 0),
                "I" | "L" => write_next_arg::<u32>(&mut reg_offset, regs, &mut env.mem, 0),
                "q" => write_next_arg::<i64>(&mut reg_offset, regs, &mut env.mem, 0),
                "Q" => write_next_arg::<u64>(&mut reg_offset, regs, &mut env.mem, 0),
                "*" => write_next_arg::<MutPtr<u8>>(&mut reg_offset, regs, &mut env.mem, MutPtr::null()),
                _ if arg_type.starts_with('^') => {
                    write_next_arg::<MutVoidPtr>(&mut reg_offset, regs, &mut env.mem, MutVoidPtr::null())
                }
                _ => unimplemented!("default unset arg for {arg_type}"),
            }
            continue;
        };
        // TODO: refactor and simplify
        match arg_type {
            "@" => {
                let arg: ConstPtr<id> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<id>(&mut reg_offset, regs, &mut env.mem, arg_val);
            },
            "f" => {
                let arg: ConstPtr<f32> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<f32>(&mut reg_offset, regs, &mut env.mem, arg_val);
            },
            "d" => {
                let arg: ConstPtr<f64> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<f64>(&mut reg_offset, regs, &mut env.mem, arg_val);
            },
            "c" | "B" => {
                let arg: ConstPtr<u8> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<u8>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "s" => {
                let arg: ConstPtr<i16> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<i16>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "S" => {
                let arg: ConstPtr<u16> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<u16>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "i" | "l" => {
                let arg: ConstPtr<i32> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<i32>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "I" | "L" => {
                let arg: ConstPtr<u32> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<u32>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "q" => {
                let arg: ConstPtr<i64> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<i64>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "Q" => {
                let arg: ConstPtr<u64> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<u64>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            "*" => {
                let arg: ConstPtr<MutPtr<u8>> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<MutPtr<u8>>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            // pointer cases
            _ if arg_type.starts_with('^') => {
                let arg: ConstPtr<MutVoidPtr> = arg_slot.cast().cast_const();
                let arg_val = env.mem.read(arg);
                let regs = env.cpu.regs_mut();
                write_next_arg::<MutVoidPtr>(&mut reg_offset, regs, &mut env.mem, arg_val);
            }
            _ => unimplemented!("write_next_arg for {arg_type}")
        }
    }

    // actual invocation
    objc_msgSend(env, target, selector.unwrap());

    store_return_value(env, this, &ret_type);

    let regs = env.cpu.regs_mut(); // re-borrow
    regs[Cpu::SP] = old_sp;
}

- (())getReturnValue:(MutVoidPtr)ret_loc {
    let sig = env.objc.borrow::<NSInvocationHostObject>(this).sig;
    let ret_type_ptr: ConstPtr<u8> = msg![env; sig methodReturnType];
    let ret_type = env.mem.cstr_at_utf8(ret_type_ptr).unwrap();

    if ret_type == "v" {
        return;
    }

    let ret_val = env.objc.borrow::<NSInvocationHostObject>(this).return_value;
    let Some(ret_val) = ret_val else {
        log!(
            "Warning: NSInvocation {:?} getReturnValue called before invoke for return type {}",
            this,
            ret_type
        );
        return;
    };

    let size = scalar_size_for_type(ret_type).unwrap_or_else(|| {
        unimplemented!("NSInvocation getReturnValue size for {ret_type}")
    });
    let src = env.mem.bytes_at(ret_val.cast().cast_const(), size.try_into().unwrap()).to_vec();
    env.mem.bytes_at_mut(ret_loc.cast(), size.try_into().unwrap()).copy_from_slice(&src);
}

- (())dealloc {
    let &NSInvocationHostObject { sig, target, arguments_retained, .. } = env.objc.borrow::<NSInvocationHostObject>(this);
    release(env, sig);
    if arguments_retained {
        release(env, target);
        let retained_objects = std::mem::take(
            &mut env.objc.borrow_mut::<NSInvocationHostObject>(this).retained_objects
        );
        for obj in retained_objects {
            release(env, obj);
        }
        let copied_strings = std::mem::take(
            &mut env.objc.borrow_mut::<NSInvocationHostObject>(this).copied_strings
        );
        for s in copied_strings {
            env.mem.free(s.cast());
        }
    } else {
        assert!(env.objc.borrow::<NSInvocationHostObject>(this).retained_objects.is_empty());
        assert!(env.objc.borrow::<NSInvocationHostObject>(this).copied_strings.is_empty());
    }
    if let Some(ptr) = env.objc.borrow_mut::<NSInvocationHostObject>(this).return_value.take() {
        env.mem.free(ptr.cast());
    }
    for ptr in env.objc.borrow::<NSInvocationHostObject>(this).arguments.iter().flatten() {
        env.mem.free(ptr.cast());
    }
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};
