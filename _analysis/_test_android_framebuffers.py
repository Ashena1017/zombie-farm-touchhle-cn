"""Test the production Android FBO adapter against isolated fake host contexts.

Extracts the actual Rust structures and methods, rather than a Python rewrite.
The fake driver deliberately returns zero for binding queries like MuMu does.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'touchHLE/touchHLE-fork/src/gles/gles1_native.rs'
OUT = ROOT / '_analysis/dumps/android-daynight-20261115'


def block(source, marker):
    start = source.index(marker)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    source = SOURCE.read_text(encoding='utf-8')
    pieces = []
    for name in ['NativeBindings', 'SharedFramebuffers', 'SharedFramebuffer']:
        pieces.append('#[derive(Default)]\n' + block(source, 'struct ' + name + ' {'))
    pieces += ['#[derive(Clone, Copy)]\n' + block(source, 'enum FramebufferAttachment {'),
               block(source, "pub struct GLES1Native<'gl_ctx>"),
               block(source, "impl GLES1Native<'_> {")]
    methods = ['GetIntegerv', 'GenFramebuffersOES', 'IsFramebufferOES', 'BindFramebufferOES',
               'BindRenderbufferOES', 'FramebufferRenderbufferOES', 'FramebufferTexture2DOES',
               'GetFramebufferAttachmentParameterivOES', 'DeleteFramebuffersOES', 'DeleteRenderbuffersOES']
    pieces.append("impl GLES1Native<'_> {\n" + '\n'.join(
        block(source, 'unsafe fn ' + name + '(') for name in methods) + '\n}')
    production = '\n\n'.join(pieces)
    production = production.replace('#[cfg(target_os = "android")]', '')
    # IsFramebuffer's desktop fallback is not part of the Android adapter.
    production = production.replace('#[cfg(not(target_os = "android"))]\n        gles11::IsFramebufferOES(renderbuffer)', '')
    harness = r'''
#![allow(non_snake_case, dead_code, unused_unsafe)]
use std::{cell::RefCell, collections::HashMap, rc::Rc, marker::PhantomData};
type GLuint=u32; type GLenum=u32; type GLint=i32; type GLsizei=i32; type GLboolean=u8;
mod gles11 {
    use super::*;
    pub const FRAMEBUFFER_OES:u32=0x8d40;
    pub const RENDERBUFFER_OES:u32=0x8d41;
    pub const FRAMEBUFFER_BINDING_OES:u32=0x8ca6;
    pub const RENDERBUFFER_BINDING_OES:u32=0x8ca7;
    pub const TEXTURE_2D:u32=0xde1;
    pub const TEXTURE:u32=0x1702;
    pub const COLOR_ATTACHMENT0_OES:u32=0x8ce0;
    pub const DEPTH_ATTACHMENT_OES:u32=0x8d00;
    pub const STENCIL_ATTACHMENT_OES:u32=0x8d20;
    pub const FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE_OES:u32=0x8cd0;
    pub const FRAMEBUFFER_ATTACHMENT_OBJECT_NAME_OES:u32=0x8cd1;
    #[derive(Default)] pub struct Host { next:u32, pub bound:u32, pub objects:HashMap<u32,HashMap<u32,u32>>, pub queries:usize }
    thread_local! { pub static HOST:RefCell<Host>=RefCell::default(); }
    pub unsafe fn GenFramebuffersOES(n:i32, out:*mut u32) {
        HOST.with(|h| {let mut h=h.borrow_mut(); for i in 0..n as usize {h.next+=1;out.add(i).write(h.next);}});
    }
    pub unsafe fn BindFramebufferOES(_:u32,name:u32) {
        HOST.with(|h| {let mut h=h.borrow_mut();h.bound=name;if name!=0 {h.objects.entry(name).or_default();}});
    }
    pub unsafe fn DeleteFramebuffersOES(n:i32,names:*const u32) {
        HOST.with(|h| {let mut h=h.borrow_mut();for i in 0..n as usize {let name=names.add(i).read();h.objects.remove(&name);if h.bound==name {h.bound=0;}}});
    }
    pub unsafe fn FramebufferTexture2DOES(_:u32,attachment:u32,_:u32,texture:u32,_:i32) {
        HOST.with(|h| {let mut h=h.borrow_mut();let bound=h.bound;h.objects.entry(bound).or_default().insert(attachment,texture);});
    }
    pub unsafe fn FramebufferRenderbufferOES(t:u32,a:u32,r:u32,name:u32) {FramebufferTexture2DOES(t,a,r,name,0);}
    pub unsafe fn BindRenderbufferOES(_:u32,_:u32) {}
    pub unsafe fn DeleteRenderbuffersOES(_:i32,_:*const u32) {}
    pub unsafe fn GetIntegerv(name:u32,out:*mut i32) {
        out.write(if name==FRAMEBUFFER_BINDING_OES || name==RENDERBUFFER_BINDING_OES {0} else {77});
    }
    pub unsafe fn GetFramebufferAttachmentParameterivOES(_:u32,_:u32,_:u32,out:*mut i32) {
        HOST.with(|h|h.borrow_mut().queries+=1);
        // Model a host that cannot answer attachment queries correctly.
        out.write(-99);
    }
}
// PRODUCTION

fn active(state:&mut NativeBindings)->GLES1Native<'_> {GLES1Native{_gl_lifetime:PhantomData,bindings:state}}
fn reset_host(){gles11::HOST.with(|h|*h.borrow_mut()=Default::default());}
fn generate(state:&mut NativeBindings)->u32 {let mut name=0;unsafe{active(state).GenFramebuffersOES(1,&mut name)};name}
fn bound_attachment(attachment:u32)->u32 {gles11::HOST.with(|h| {let h=h.borrow();h.objects[&h.bound][&attachment]})}
fn query(state:&mut NativeBindings,pname:u32)->i32 {let mut v=-1;unsafe{active(state).GetIntegerv(pname,&mut v)};v}
fn attachment_query(state:&mut NativeBindings,target:u32,attachment:u32,pname:u32)->i32 {
    let mut value=-1;unsafe{active(state).GetFramebufferAttachmentParameterivOES(target,attachment,pname,&mut value)};value
}

#[test] fn loading_context_fbo_is_recreated_in_main_context() {
    reset_host(); let mut main=NativeBindings::default();let mut loader=NativeBindings::default();
    loader.shared=main.shared.clone();let screen=generate(&mut main);
    unsafe{active(&mut main).BindFramebufferOES(gles11::FRAMEBUFFER_OES,screen)};
    let main_host=gles11::HOST.with(|h|std::mem::take(&mut *h.borrow_mut()));
    let mask=generate(&mut loader);assert_ne!(screen,mask);
    unsafe{let mut gl=active(&mut loader);gl.BindFramebufferOES(gles11::FRAMEBUFFER_OES,mask);
        gl.FramebufferTexture2DOES(gles11::FRAMEBUFFER_OES,0x8ce0,gles11::TEXTURE_2D,21,0);}
    assert_eq!(bound_attachment(0x8ce0),21);
    gles11::HOST.with(|h|*h.borrow_mut()=main_host);
    unsafe{active(&mut main).BindFramebufferOES(gles11::FRAMEBUFFER_OES,mask)};
    assert_eq!(bound_attachment(0x8ce0),21);
    assert_eq!(query(&mut main,gles11::FRAMEBUFFER_BINDING_OES),mask as i32);
    assert_eq!(gles11::HOST.with(|h|h.borrow().bound),2);
}
#[test] fn attachment_updates_and_detaches_propagate() {
    reset_host();let mut a=NativeBindings::default();let name=generate(&mut a);
    let mut b=NativeBindings::default();b.shared=a.shared.clone();
    unsafe{active(&mut a).BindFramebufferOES(gles11::FRAMEBUFFER_OES,name);
        active(&mut a).FramebufferTexture2DOES(gles11::FRAMEBUFFER_OES,0x8ce0,gles11::TEXTURE_2D,21,0);}
    let host_a=gles11::HOST.with(|h|std::mem::take(&mut *h.borrow_mut()));
    unsafe{active(&mut b).BindFramebufferOES(gles11::FRAMEBUFFER_OES,name);
        active(&mut b).FramebufferTexture2DOES(gles11::FRAMEBUFFER_OES,0x8ce0,gles11::TEXTURE_2D,0,0);}
    gles11::HOST.with(|h|*h.borrow_mut()=host_a);
    unsafe{active(&mut a).BindFramebufferOES(gles11::FRAMEBUFFER_OES,name)};
    assert_eq!(bound_attachment(0x8ce0),0);
}
#[test] fn framebuffer_lifecycle_and_deleted_host_cleanup() {
    reset_host();let mut a=NativeBindings::default();let name=generate(&mut a);
    unsafe{assert_eq!(active(&mut a).IsFramebufferOES(name),0);
        active(&mut a).BindFramebufferOES(gles11::FRAMEBUFFER_OES,name);
        assert_eq!(active(&mut a).IsFramebufferOES(name),1);}
    let mut b=NativeBindings::default();b.shared=a.shared.clone();
    unsafe{active(&mut b).DeleteFramebuffersOES(1,&name);
        active(&mut a).BindFramebufferOES(gles11::FRAMEBUFFER_OES,0);
        assert_eq!(active(&mut a).IsFramebufferOES(name),0);}
    assert!(a.local.is_empty());assert!(gles11::HOST.with(|h|h.borrow().objects.is_empty()));
    assert!(generate(&mut a)>name);
}
#[test] fn deleting_bound_framebuffer_resets_binding() {
    reset_host();let mut state=NativeBindings::default();let name=generate(&mut state);
    unsafe{active(&mut state).BindFramebufferOES(gles11::FRAMEBUFFER_OES,name);
        active(&mut state).DeleteFramebuffersOES(1,&name);}
    assert_eq!(query(&mut state,gles11::FRAMEBUFFER_BINDING_OES),0);
}
#[test] fn renderbuffer_binding_survives_broken_driver_queries() {
    reset_host();let mut state=NativeBindings::default();
    unsafe{active(&mut state).BindRenderbufferOES(gles11::RENDERBUFFER_OES,12)};
    assert_eq!(query(&mut state,gles11::RENDERBUFFER_BINDING_OES),12);
    unsafe{active(&mut state).DeleteRenderbuffersOES(1,&12)};
    assert_eq!(query(&mut state,gles11::RENDERBUFFER_BINDING_OES),0);
    assert_eq!(query(&mut state,123),77);
}
#[test] fn independent_sharegroups_keep_independent_namespaces() {
    reset_host();let mut a=NativeBindings::default();let mut b=NativeBindings::default();
    assert_eq!(generate(&mut a),1);assert_eq!(generate(&mut b),1);
    unsafe{active(&mut a).BindFramebufferOES(gles11::FRAMEBUFFER_OES,1)};
    assert!(!b.shared.borrow().objects[&1].instantiated);
}
#[test] fn renderbuffer_attachment_queries_do_not_call_broken_encoder() {
    reset_host();let mut state=NativeBindings::default();let name=generate(&mut state);
    unsafe{let mut gl=active(&mut state);gl.BindFramebufferOES(gles11::FRAMEBUFFER_OES,name);
        gl.FramebufferRenderbufferOES(gles11::FRAMEBUFFER_OES,0x8ce0,gles11::RENDERBUFFER_OES,12);}
    assert_eq!(attachment_query(&mut state,0x8d40,0x8ce0,0x8cd0),0x8d41);
    assert_eq!(attachment_query(&mut state,0x8d40,0x8ce0,0x8cd1),12);
    assert_eq!(gles11::HOST.with(|h|h.borrow().queries),0);
}
#[test] fn shared_texture_queries_follow_attachment_changes_and_detach() {
    reset_host();let mut a=NativeBindings::default();let name=generate(&mut a);
    let mut b=NativeBindings::default();b.shared=a.shared.clone();
    unsafe{active(&mut a).BindFramebufferOES(0x8d40,name);
        active(&mut a).FramebufferTexture2DOES(0x8d40,0x8ce0,gles11::TEXTURE_2D,21,0);
        active(&mut b).BindFramebufferOES(0x8d40,name);}
    assert_eq!(attachment_query(&mut b,0x8d40,0x8ce0,0x8cd0),0x1702);
    assert_eq!(attachment_query(&mut b,0x8d40,0x8ce0,0x8cd1),21);
    unsafe{active(&mut a).FramebufferTexture2DOES(0x8d40,0x8ce0,gles11::TEXTURE_2D,0,0);}
    assert_eq!(attachment_query(&mut b,0x8d40,0x8ce0,0x8cd0),0);
    // Invalid OBJECT_NAME on NONE must still reach native error validation.
    assert_eq!(attachment_query(&mut b,0x8d40,0x8ce0,0x8cd1),-99);
    assert_eq!(gles11::HOST.with(|h|h.borrow().queries),1);
}
#[test] fn invalid_attachment_queries_keep_native_validation() {
    reset_host();let mut state=NativeBindings::default();let name=generate(&mut state);
    unsafe{active(&mut state).BindFramebufferOES(0x8d40,name);}
    assert_eq!(attachment_query(&mut state,0x8d40,0x8ce0,0x8cd0),0);
    assert_eq!(attachment_query(&mut state,123,0x8ce0,0x8cd0),-99);
    assert_eq!(attachment_query(&mut state,0x8d40,123,0x8cd0),-99);
    assert_eq!(attachment_query(&mut state,0x8d40,0x8ce0,123),-99);
    unsafe{active(&mut state).BindFramebufferOES(0x8d40,0);}
    assert_eq!(attachment_query(&mut state,0x8d40,0x8ce0,0x8cd0),-99);
    assert_eq!(gles11::HOST.with(|h|h.borrow().queries),4);
}
'''.replace('// PRODUCTION', production)
    OUT.mkdir(parents=True, exist_ok=True)
    test_source = OUT / 'framebuffer-tests.rs'
    test_source.write_text(harness, encoding='utf-8')
    rustc = ROOT / 'touchHLE/_build_tools/cargo/bin/rustc.exe'
    env = __import__('os').environ.copy()
    env['RUSTUP_HOME'] = str(ROOT / 'touchHLE/_build_tools/rustup')
    subprocess.run([str(rustc), '--edition=2021', '--test', str(test_source),
                    '-o', str(OUT / 'framebuffer-tests.exe')], check=True, env=env)
    result = subprocess.run([str(OUT / 'framebuffer-tests.exe'), '--test-threads=1'],
                            check=True, capture_output=True, text=True)
    print(result.stdout)
    (OUT / 'framebuffer-tests.txt').write_text(result.stdout, encoding='utf-8')


if __name__ == '__main__':
    main()
