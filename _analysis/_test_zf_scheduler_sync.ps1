param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$fork = Join-Path $root 'touchHLE\touchHLE-fork'
$dump = Join-Path $PSScriptRoot 'dumps'
$source = Join-Path $dump 'zf-scheduler-sync-harness.rs'
$binary = Join-Path $dump 'zf-scheduler-sync-tests.exe'
$rustc = Join-Path $root 'touchHLE\_build_tools\rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\rustc.exe'
$schedulerPath = (Join-Path $fork 'src\objc\zombie_farm_scheduler.rs').Replace('\', '\\')
$mutexPath = (Join-Path $fork 'src\environment\mutex.rs').Replace('\', '\\')
$nsObject = [IO.File]::ReadAllText((Join-Path $fork 'src\frameworks\foundation\ns_object.rs'), [Text.Encoding]::UTF8)
$method = [regex]::Match($nsObject, '(?ms)^fn method_imp_for_class\(.*?^}')
if (-not $method.Success) { throw 'Could not extract production method_imp_for_class' }
$methodSource = $method.Value.Replace('fn method_imp_for_class(', 'pub(crate) fn method_imp_for_class(')

# Compile the production Cocos gate module, unchanged IMP lookup and guest mutex
# implementation against a small non-graphical environment. These are routing
# and recursive-mutex unit checks, not a real guest CPU/ABI test. No game/saves.
$harness = @'
#![allow(dead_code)]
use std::collections::HashMap;
type ThreadId = usize;
macro_rules! log { ($($args:tt)*) => {}; }
macro_rules! log_dbg { ($($args:tt)*) => {}; }
mod libc { pub mod errno { pub const EBUSY:i32=16; pub const EDEADLK:i32=35; pub const EPERM:i32=1; } }
mod environment {
    use crate::{Environment, ThreadId};
    #[path = "__MUTEX_PATH__"] mod actual_mutex;
    pub use actual_mutex::{MutexState, MutexType, MutexId};
}
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
struct Ptr(u32);
impl Ptr { fn null() -> Self { Self(0) } }
mod abi {
    use crate::{Environment, Ptr};
    #[derive(Clone, Copy)] pub struct GuestFunction(pub u32);
    impl GuestFunction {
        pub fn to_ptr(self) -> Ptr { Ptr(self.0) }
        pub fn call_without_pushing_stack_frame(self, env: &mut Environment) {
            let callback = env.callbacks[&self.0];
            callback(env);
        }
    }
}
mod objc {
    use super::*;
    pub type Class = u32;
    pub type SEL = u32;
    #[allow(non_upper_case_globals)] pub const nil: Class = 0;
    pub enum IMP { Guest(crate::abi::GuestFunction), Host(()) }
    pub struct ClassHostObject { pub name:String, pub superclass:Class }
    impl ClassHostObject { fn as_any(&self) -> &dyn std::any::Any { self } }
    pub struct ObjC {
        pub zombie_farm_scheduler_mutex: Option<environment::MutexId>,
        pub classes: HashMap<Class, ClassHostObject>,
        pub method: Option<IMP>,
    }
    impl ObjC {
        fn get_host_object(&self, class:Class) -> Option<&ClassHostObject> { self.classes.get(&class) }
        pub fn class_get_method_imp(&self, _class:Class, _sel:SEL) -> Option<&IMP> { self.method.as_ref() }
    }
    #[path = "__SCHEDULER_PATH__"] pub(crate) mod zombie_farm_scheduler;
    #[cfg(test)] mod integration_tests {
        use super::*;
        fn inner(env: &mut Environment) {
            let mutex = env.objc.zombie_farm_scheduler_mutex.unwrap();
            assert!(env.mutex_state.mutex_is_locked_by(mutex, env.current_thread));
            assert_eq!(env.lock_mutex(mutex).unwrap(), 4);
            assert_eq!(env.unlock_mutex(mutex).unwrap(), 3);
            assert_eq!(env.cpu.regs, [0x11223344; 16]);
            assert_eq!(env.cpu.stack, vec![0x3f800000, 1]);
            env.calls.push(3);
        }
        fn action_manager(env: &mut Environment) {
            zombie_farm_scheduler::call_guest_imp(env, 3, abi::GuestFunction(3));
            let mutex = env.objc.zombie_farm_scheduler_mutex.unwrap();
            assert!(env.mutex_state.mutex_is_locked_by(mutex, env.current_thread));
            assert_eq!(env.lock_mutex(mutex).unwrap(), 3);
            assert_eq!(env.unlock_mutex(mutex).unwrap(), 2);
            env.calls.push(2);
        }
        fn outer(env: &mut Environment) {
            zombie_farm_scheduler::call_guest_imp(env, 5, abi::GuestFunction(2));
            let mutex = env.objc.zombie_farm_scheduler_mutex.unwrap();
            assert!(env.mutex_state.mutex_is_locked_by(mutex, env.current_thread));
            env.calls.push(1);
        }
        #[test] fn tick_action_scheduler_callbacks_share_one_recursive_gate() {
            let mut env = Environment::new();
            env.callbacks.insert(1, outer);
            env.callbacks.insert(2, action_manager);
            env.callbacks.insert(3, inner);
            zombie_farm_scheduler::call_guest_imp(&mut env, 2, abi::GuestFunction(1));
            assert_eq!(env.calls, vec![3,2,1]);
            let mutex = env.objc.zombie_farm_scheduler_mutex.unwrap();
            assert!(!env.mutex_state.mutex_is_locked(mutex));
            assert_eq!(env.cpu.regs, [0x11223344; 16]);
            assert_eq!(env.cpu.stack, vec![0x3f800000,1]);
        }
        #[test] fn unrelated_guest_methods_do_not_create_a_scheduler_mutex() {
            let mut env = Environment::new();
            env.callbacks.insert(1, |env| env.calls.push(1));
            zombie_farm_scheduler::call_guest_imp(&mut env, 1, abi::GuestFunction(1));
            assert_eq!(env.calls, vec![1]);
            assert!(env.objc.zombie_farm_scheduler_mutex.is_none());
        }
    }
}
struct Bundle { id:String, version:String }
impl Bundle {
    fn bundle_identifier(&self) -> &str { &self.id }
    fn bundle_version(&self) -> &str {
        assert!(!self.version.is_empty(), "missing CFBundleVersion");
        &self.version
    }
}
struct Cpu { regs:[u32;16], stack:Vec<u32> }
struct Dyld;
impl Dyld {
    fn create_proc_address(&mut self, _mem:&mut (), _cpu:&mut Cpu, name:&str) -> Option<abi::GuestFunction> {
        assert_eq!(name, "_objc_msgSend");
        Some(abi::GuestFunction(0xd15a7c))
    }
}
struct Environment {
    bundle:Bundle, objc:objc::ObjC, mutex_state:environment::MutexState,
    current_thread:ThreadId, cpu:Cpu, mem:(), dyld:Dyld,
    callbacks:HashMap<u32,fn(&mut Environment)>, calls:Vec<u32>,
    on_block:Option<fn(&mut Environment,environment::MutexId)>,
}
impl Environment {
    fn new() -> Self {
        Self {
            bundle:Bundle { id:"com.playforge.ZombieFarm.ZFR".into(), version:"1.0".into() },
            objc:objc::ObjC {
                zombie_farm_scheduler_mutex:None,
                classes:HashMap::from([
                    (1,objc::ClassHostObject{name:"NSObject".into(), superclass:0}),
                    (2,objc::ClassHostObject{name:"CCScheduler".into(), superclass:1}),
                    (3,objc::ClassHostObject{name:"InheritedScheduler".into(), superclass:2}),
                    (4,objc::ClassHostObject{name:"CCActionManager".into(), superclass:1}),
                    (5,objc::ClassHostObject{name:"InheritedActionManager".into(), superclass:4}),
                ]),
                method:Some(objc::IMP::Guest(abi::GuestFunction(0x22be3d))),
            },
            mutex_state:Default::default(), current_thread:0,
            cpu:Cpu{regs:[0x11223344;16],stack:vec![0x3f800000,1]}, mem:(), dyld:Dyld,
            callbacks:HashMap::new(), calls:vec![], on_block:None,
        }
    }
    fn block_on_mutex(&mut self, mutex:environment::MutexId) {
        self.on_block.expect("unexpected guest-thread blocking")(self,mutex);
    }
}
mod foundation_routing {
    use crate::{Environment,Ptr as ConstVoidPtr};
    use crate::objc::{Class,SEL,IMP};
__METHOD_SOURCE__
}
#[test] fn cached_guest_imps_keep_the_selected_implementation() {
    let mut env = Environment::new();
    for class in [2,3,4,5] {
        assert_eq!(foundation_routing::method_imp_for_class(&mut env,class,17),Ptr(0x22be3d));
    }
    assert_eq!(foundation_routing::method_imp_for_class(&mut env,1,17),Ptr(0x22be3d));
    env.bundle.version = "1.1".into();
    assert_eq!(foundation_routing::method_imp_for_class(&mut env,2,17),Ptr(0x22be3d));
    env.bundle.id = "unrelated.app.picker".into();
    env.bundle.version.clear();
    assert_eq!(foundation_routing::method_imp_for_class(&mut env,2,17),Ptr(0x22be3d));
    env.objc.method = None;
    assert_eq!(foundation_routing::method_imp_for_class(&mut env,2,17),Ptr::null());
}
#[test] fn guest_contention_suspends_waiter_and_relocks_after_owner_finishes() {
    let mut env = Environment::new();
    let mutex = env.mutex_state.init_mutex(environment::MutexType::PTHREAD_MUTEX_RECURSIVE);
    assert_eq!(env.lock_mutex(mutex).unwrap(),1);
    env.current_thread = 4;
    env.on_block = Some(|env,mutex| {
        assert_eq!(env.current_thread,4);
        assert!(env.mutex_state.mutex_is_locked_by(mutex,0));
        env.current_thread = 0;
        assert_eq!(env.unlock_mutex(mutex).unwrap(),0);
        env.current_thread = 4;
        env.relock_unblocked_mutex_for_thread(4,mutex);
    });
    assert_eq!(env.lock_mutex(mutex).unwrap(),1);
    assert!(env.mutex_state.mutex_is_locked_by(mutex,4));
    assert_eq!(env.unlock_mutex(mutex).unwrap(),0);
}
'@
$harness = $harness.Replace('__MUTEX_PATH__', $mutexPath).Replace('__SCHEDULER_PATH__', $schedulerPath).Replace('__METHOD_SOURCE__', $methodSource)
[IO.File]::WriteAllText($source, $harness, [Text.UTF8Encoding]::new($false))
& $rustc --edition=2021 --test $source -o $binary
if ($LASTEXITCODE -ne 0) { throw "rustc failed: $LASTEXITCODE" }
& $binary --nocapture
if ($LASTEXITCODE -ne 0) { throw "Scheduler synchronization tests failed: $LASTEXITCODE" }
