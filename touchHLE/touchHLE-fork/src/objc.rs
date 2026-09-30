/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Objective-C runtime.
//!
//! Apple's [Programming with Objective-C](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Introduction/Introduction.html)
//! is a useful introduction to the language from a user's perspective.
//! There are further resources in the child modules of this module, but they
//! are more implementation-specific.
//!
//! The strategy for this emulator will be to provide our own implementations of
//! an Objective-C runtime and libraries for it (Foundation etc). These
//! implementations will be "host code": Rust code forming part of the emulator,
//! not emulated code. The runtime will need to be able to handle classes that
//! originate from the guest app, classes defined by the host, and sometimes
//! classes that are both (considering Objective-C's support for inheritance,
//! categories and dynamic class editing).

use crate::dyld::{export_c_func, ConstantExports, FunctionExports, HostConstant, HostDylib};
use crate::frameworks::foundation::ns_string;
use crate::objc::messages::ThreadInitializer;
use crate::MutexId;
use std::collections::{HashMap, VecDeque};

mod classes;
mod messages;
mod methods;
mod objects;
mod properties;
mod selectors;
mod synchronization;

pub use classes::{objc_classes, Class, ClassExports, ClassTemplate};
pub use messages::{
    autorelease, msg, msg_class, msg_send, msg_send_no_type_checking, msg_send_super2, msg_super,
    objc_super, release, retain, zombie_farm_complete_all_quests_cheat,
    zombie_farm_zoom_step,
};
pub use methods::{HostIMP, IMP};
pub use objects::{
    id, impl_HostObject_with_superclass, nil, AnyHostObject, HostObject, TrivialHostObject,
};
pub use properties::todo_objc_setter;
pub use selectors::{selector, SEL};

use crate::mem::{ConstVoidPtr, MutPtr, MutVoidPtr};
use crate::Environment;
use classes::{
    class_getInstanceSize, class_getSuperclass, objc_getClass, ClassHostObject, FakeClass,
    UnimplementedClass,
};
pub(crate) use messages::objc_msgSend;
use messages::{objc_msgSendSuper2, objc_msgSend_stret, MsgSendSignature, MsgSendSuperSignature};
use methods::method_list_t;
use objects::{objc_object, object_getClass, HostObjectEntry};
use properties::{ivar_list_t, objc_copyStruct, objc_getProperty, objc_setProperty};
use selectors::sel_registerName;
use std::cell::RefCell;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Mutex as StdMutex, OnceLock};
use synchronization::{objc_sync_enter, objc_sync_exit};

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub(super) struct MethodCacheKey {
    class: Class,
    selector: SEL,
    super_lookup: bool,
}

#[derive(Clone, Copy)]
pub(super) struct MethodCacheValue {
    implementation_class: Class,
    imp: IMP,
}

/// Typedef for `NSZone *`. This is a [fossil type] found in the signature of
/// `allocWithZone:` and similar methods. Its value is always ignored.
///
/// [fossil type]: https://en.wiktionary.org/wiki/fossil_word
pub type NSZonePtr = crate::mem::MutVoidPtr;

/// Main type holding Objective-C runtime state.
pub struct ObjC {
    /// Known selectors (interned method name strings).
    selectors: HashMap<String, SEL>,

    /// Reverse map for selectors so hot message dispatch can get a stable
    /// string without allocating.
    selector_names: HashMap<SEL, &'static str>,

    /// Mapping of known (guest) object pointers to their host objects.
    ///
    /// If an object isn't in this map, we will consider it not to exist.
    objects: HashMap<id, HostObjectEntry>,

    /// Known classes.
    ///
    /// Look at the `isa` to get the metaclass for a class.
    classes: HashMap<String, Class>,

    /// Cache from an Objective-C lookup starting point to the class that
    /// actually provides the method.
    method_cache: RefCell<HashMap<MethodCacheKey, MethodCacheValue>>,

    /// Stable class names for hot debug/workaround checks.
    class_names: RefCell<HashMap<Class, &'static str>>,

    /// Mutexes used in @synchronized blocks (objc_sync_enter/exit).
    sync_mutexes: HashMap<id, MutexId>,

    /// Mutexes for running the +initialize function.
    initializer_threads: HashMap<id, ThreadInitializer>,

    /// Temporary storage for optional type information when sending a message.
    /// Type information isn't part of the `objc_msgSend` ABI, so an alternative
    /// channel is needed.
    message_type_info: Option<(std::any::TypeId, &'static str)>,

    /// Debug info for the most recently dispatched Objective-C message.
    last_message_debug: Option<ObjCMessageDebug>,
}

#[derive(Clone, Copy)]
pub(crate) struct ObjCMessageDebug {
    pub receiver: id,
    pub selector: SEL,
    pub receiver_class: Option<Class>,
}

impl ObjC {
    pub fn new() -> ObjC {
        ObjC {
            selectors: HashMap::new(),
            selector_names: HashMap::new(),
            objects: HashMap::new(),
            classes: HashMap::new(),
            method_cache: RefCell::new(HashMap::new()),
            class_names: RefCell::new(HashMap::new()),
            sync_mutexes: HashMap::new(),
            initializer_threads: HashMap::new(),
            message_type_info: None,
            last_message_debug: None,
        }
    }
}

static LAST_MESSAGE_RECEIVER: AtomicU32 = AtomicU32::new(0);
static LAST_MESSAGE_SELECTOR: AtomicU32 = AtomicU32::new(0);
static LAST_MESSAGE_CLASS: AtomicU32 = AtomicU32::new(0);
static ZOMBIE_FARM_MESSAGE_SEQUENCE: AtomicU32 = AtomicU32::new(0);

#[derive(Clone, Copy)]
struct ZombieFarmMessageTrace {
    sequence: u32,
    receiver: u32,
    selector: u32,
    selector_name: &'static str,
    receiver_class: u32,
    pc: u32,
    lr: u32,
    sp: u32,
    fp: u32,
    cpsr: u32,
}

static ZOMBIE_FARM_RECENT_MESSAGES: OnceLock<StdMutex<VecDeque<ZombieFarmMessageTrace>>> =
    OnceLock::new();

pub(crate) fn record_zombie_farm_message_trace(
    debug: ObjCMessageDebug,
    selector_name: &'static str,
    regs: &[u32; 16],
    cpsr: u32,
) {
    const TRACE_CAPACITY: usize = 32;
    let trace = ZombieFarmMessageTrace {
        sequence: ZOMBIE_FARM_MESSAGE_SEQUENCE.fetch_add(1, Ordering::Relaxed),
        receiver: debug.receiver.to_bits(),
        selector: debug.selector.to_bits(),
        selector_name,
        receiver_class: debug.receiver_class.map_or(0, |class| class.to_bits()),
        pc: regs[crate::cpu::Cpu::PC],
        lr: regs[crate::cpu::Cpu::LR],
        sp: regs[crate::cpu::Cpu::SP],
        fp: regs[crate::abi::FRAME_POINTER],
        cpsr,
    };
    let recent = ZOMBIE_FARM_RECENT_MESSAGES.get_or_init(|| StdMutex::new(VecDeque::new()));
    let mut recent = recent.lock().unwrap();
    if recent.len() == TRACE_CAPACITY {
        recent.pop_front();
    }
    recent.push_back(trace);
}

pub(crate) fn dump_zombie_farm_message_trace() {
    let Some(recent) = ZOMBIE_FARM_RECENT_MESSAGES.get() else {
        return;
    };
    let Ok(recent) = recent.lock() else {
        return;
    };
    echo_no_panic!("Recent ZombieFarm ObjC messages before CPU error:");
    for trace in recent.iter() {
        echo_no_panic!(
            "  #{:08x} receiver=0x{:08x} selector=0x{:08x} ({}) class=0x{:08x} pc=0x{:08x} lr=0x{:08x} sp=0x{:08x} fp=0x{:08x} mode={}",
            trace.sequence,
            trace.receiver,
            trace.selector,
            trace.selector_name,
            trace.receiver_class,
            trace.pc,
            trace.lr,
            trace.sp,
            trace.fp,
            if trace.cpsr & crate::cpu::Cpu::CPSR_THUMB != 0 {
                "Thumb"
            } else {
                "ARM"
            },
        );
    }
}

pub(crate) fn last_message_debug_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| {
        cfg!(debug_assertions)
            || std::env::var("TOUCHHLE_OBJC_LAST_MESSAGE_DEBUG")
                .ok()
                .as_deref()
                == Some("1")
    })
}

pub(crate) fn set_global_last_message_debug(debug: ObjCMessageDebug) {
    LAST_MESSAGE_RECEIVER.store(debug.receiver.to_bits(), Ordering::Relaxed);
    LAST_MESSAGE_SELECTOR.store(debug.selector.to_bits(), Ordering::Relaxed);
    LAST_MESSAGE_CLASS.store(
        debug.receiver_class.map_or(0, |class| class.to_bits()),
        Ordering::Relaxed,
    );
}

pub(crate) fn global_last_message_debug() -> String {
    let selector = LAST_MESSAGE_SELECTOR.load(Ordering::Relaxed);
    if selector == 0 {
        return "none".to_string();
    }
    format!(
        "receiver=0x{:x}, selector=0x{:x}, receiver_class=0x{:x}",
        LAST_MESSAGE_RECEIVER.load(Ordering::Relaxed),
        selector,
        LAST_MESSAGE_CLASS.load(Ordering::Relaxed),
    )
}

pub const DYLIB: HostDylib = HostDylib {
    path: "/usr/lib/libobjc.A.dylib",
    aliases: &["/usr/lib/libobjc.dylib"],
    class_exports: &[],
    constant_exports: &[CONSTANTS],
    function_exports: &[FUNCTIONS],
};

const CONSTANTS: ConstantExports = &[
    // We don't use these in our Objective-C runtime, but exporting useless
    // symbols for these silences the warning about the unhandled relocation,
    // and avoids a linker error for the integration tests.
    ("__objc_empty_vtable", HostConstant::NullPtr),
    ("__objc_empty_cache", HostConstant::NullPtr),
];

/// Block support is iOS 4+, but it seems like Block Runtime Helpers
/// could still be called on even if minimal iOS version is set to 3.x?
///
/// ref. <https://clang.llvm.org/docs/Block-ABI-Apple.html#runtime-helper-functions>
fn _Block_object_dispose(_env: &mut Environment, object: ConstVoidPtr, flags: i32) {
    // `BLOCK_FIELD_IS_BYREF` flag defines an on stack structure holding
    // the __block variable. It is _probably_ safe to ignore.
    // TODO: properly implement for block support
    assert!(flags == 8); // BLOCK_FIELD_IS_BYREF
    log!(
        "Warning: Ignoring _Block_object_dispose({:?}, BLOCK_FIELD_IS_BYREF)",
        object
    );
}

fn objc_retain(env: &mut Environment, object: id) -> id {
    if object != nil {
        let _ = env.objc.try_increment_refcount(object);
    }
    object
}

fn objc_release(env: &mut Environment, object: id) {
    if object == nil {
        return;
    }

    if env.objc.try_decrement_refcount(object) == Some(true) {
        msg![env; object dealloc]
    }
}

fn objc_autorelease(env: &mut Environment, object: id) -> id {
    if object != nil && env.objc.try_get_refcount(object).is_some() {
        return autorelease(env, object);
    }
    object
}

fn objc_retainAutorelease(env: &mut Environment, object: id) -> id {
    let object = objc_retain(env, object);
    objc_autorelease(env, object)
}

fn objc_retainAutoreleasedReturnValue(env: &mut Environment, object: id) -> id {
    objc_retain(env, object)
}

fn objc_retainAutoreleaseReturnValue(env: &mut Environment, object: id) -> id {
    let object = objc_retain(env, object);
    objc_autorelease(env, object)
}

fn objc_autoreleaseReturnValue(env: &mut Environment, object: id) -> id {
    objc_autorelease(env, object)
}

fn objc_unsafeClaimAutoreleasedReturnValue(_env: &mut Environment, object: id) -> id {
    object
}

fn objc_storeStrong(env: &mut Environment, location: MutPtr<id>, object: id) {
    if location.is_null() {
        return;
    }

    let old_object: id = env.mem.read(location);
    if old_object == object {
        return;
    }

    let retained_object = objc_retain(env, object);
    env.mem.write(location, retained_object);
    objc_release(env, old_object);
}

fn objc_retainBlock(_env: &mut Environment, block: MutVoidPtr) -> MutVoidPtr {
    block
}

fn _Block_copy(_env: &mut Environment, block: MutVoidPtr) -> MutVoidPtr {
    block
}

fn _Block_release(_env: &mut Environment, _block: MutVoidPtr) {}

fn objc_exception_throw(env: &mut Environment, exception: id) {
    log!(
        "Warning: ignored objc_exception_throw: {}",
        describe_exception(env, exception)
    );
}

fn describe_exception(env: &mut Environment, exception: id) -> String {
    if exception == nil {
        return "(nil)".into();
    }

    let description: id = msg![env; exception description];
    if description == nil {
        return format!("{exception:?}");
    }
    ns_string::to_rust_string(env, description).into_owned()
}

const FUNCTIONS: FunctionExports = &[
    export_c_func!(class_getInstanceSize(_)),
    export_c_func!(class_getSuperclass(_)),
    export_c_func!(objc_msgSend(_, _)),
    export_c_func!(objc_msgSend_stret(_, _, _)),
    export_c_func!(objc_msgSendSuper2(_, _)),
    export_c_func!(objc_getClass(_)),
    export_c_func!(objc_getProperty(_, _, _, _)),
    export_c_func!(objc_setProperty(_, _, _, _, _, _)),
    export_c_func!(objc_copyStruct(_, _, _, _, _)),
    export_c_func!(objc_sync_enter(_)),
    export_c_func!(objc_sync_exit(_)),
    export_c_func!(object_getClass(_)),
    export_c_func!(sel_registerName(_)),
    export_c_func!(_Block_object_dispose(_, _)),
    export_c_func!(objc_retain(_)),
    export_c_func!(objc_release(_)),
    export_c_func!(objc_autorelease(_)),
    export_c_func!(objc_retainAutorelease(_)),
    export_c_func!(objc_retainAutoreleasedReturnValue(_)),
    export_c_func!(objc_retainAutoreleaseReturnValue(_)),
    export_c_func!(objc_autoreleaseReturnValue(_)),
    export_c_func!(objc_unsafeClaimAutoreleasedReturnValue(_)),
    export_c_func!(objc_storeStrong(_, _)),
    export_c_func!(objc_retainBlock(_)),
    export_c_func!(_Block_copy(_)),
    export_c_func!(_Block_release(_)),
    export_c_func!(objc_exception_throw(_)),
];
