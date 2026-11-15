"""Run the production viewport-scale probe against strict GLES query rules."""
import os
import subprocess
from pathlib import Path

from _test_android_framebuffers import block

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_analysis/dumps/android-cloud-20261115'


def main():
    source = (ROOT / 'touchHLE/touchHLE-fork/src/frameworks/opengles/gles_guest.rs').read_text(encoding='utf-8')
    production = block(source, 'fn zfr_gl_framebuffer_is_scaled(')
    harness = r'''
#![allow(non_snake_case, dead_code, unused_variables)]
use std::{collections::HashMap, sync::{Mutex, atomic::{AtomicU32, Ordering}}};
type GLint = i32; type GLuint = u32;
mod gles11 {
    pub const FRAMEBUFFER_OES: u32 = 0x8d40;
    pub const COLOR_ATTACHMENT0_OES: u32 = 0x8ce0;
}
static CURRENT: AtomicU32 = AtomicU32::new(0);
static ZFR_GL_FBO_IS_TEXTURE: Mutex<Option<HashMap<(usize, u32), bool>>> = Mutex::new(None);
fn zfr_gl_current_framebuffer() -> u32 { CURRENT.load(Ordering::Relaxed) }
fn zfr_gl_renderbuffer_is_drawable_backed(context: usize, name: u32) -> bool {
    context == 42 && name == 12
}
fn zfr_gl_trace_enabled() -> bool { false }
macro_rules! log { ($($arg:tt)*) => {}; }
trait GLES {
    unsafe fn GetFramebufferAttachmentParameterivOES(&mut self, target: u32,
        attachment: u32, pname: u32, params: *mut i32);
}
struct StrictDriver { object_type: i32, name: i32, queries: Vec<u32> }
impl GLES for StrictDriver {
    unsafe fn GetFramebufferAttachmentParameterivOES(&mut self, target: u32,
        attachment: u32, pname: u32, params: *mut i32) {
        assert_eq!(target, gles11::FRAMEBUFFER_OES);
        assert_eq!(attachment, gles11::COLOR_ATTACHMENT0_OES);
        self.queries.push(pname);
        params.write(match pname {
            0x8cd0 => self.object_type,
            0x8cd1 => {
                assert_ne!(self.object_type, 0, "OBJECT_NAME on NONE produces GL_INVALID_ENUM");
                self.name
            }
            _ => panic!("Unexpected attachment query"),
        });
    }
}
fn fixture(fbo: u32, object_type: i32, name: i32) -> StrictDriver {
    CURRENT.store(fbo, Ordering::Relaxed);
    *ZFR_GL_FBO_IS_TEXTURE.lock().unwrap() = None;
    StrictDriver {object_type, name, queries: vec![]}
}
// PRODUCTION
#[test] fn empty_framebuffer_is_provisional_and_never_queries_name() {
    let mut gl = fixture(1, 0, 0);
    assert!(!zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert_eq!(gl.queries, vec![0x8cd0]);
    gl.object_type = 0x8d41; gl.name = 12;
    assert!(zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert_eq!(gl.queries, vec![0x8cd0, 0x8cd0, 0x8cd1]);
}
#[test] fn drawable_renderbuffer_is_scaled_and_cached() {
    let mut gl = fixture(1, 0x8d41, 12);
    assert!(zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert!(zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert_eq!(gl.queries, vec![0x8cd0, 0x8cd1]);
}
#[test] fn app_texture_does_not_need_name_or_scaling() {
    let mut gl = fixture(1, 0x1702, 21);
    assert!(!zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert_eq!(gl.queries, vec![0x8cd0]);
}
#[test] fn app_renderbuffer_is_not_scaled() {
    let mut gl = fixture(1, 0x8d41, 99);
    assert!(!zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert_eq!(gl.queries, vec![0x8cd0, 0x8cd1]);
}
#[test] fn default_framebuffer_requires_no_attachment_queries() {
    let mut gl = fixture(0, 0, 0);
    assert!(zfr_gl_framebuffer_is_scaled(&mut gl, 42));
    assert!(gl.queries.is_empty());
}
#[test] fn drawable_lookup_is_context_specific() {
    let mut gl = fixture(1, 0x8d41, 12);
    assert!(!zfr_gl_framebuffer_is_scaled(&mut gl, 43));
    assert!(zfr_gl_framebuffer_is_scaled(&mut gl, 42));
}
'''.replace('// PRODUCTION', production)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'framebuffer-scale-tests.rs'
    path.write_text(harness, encoding='utf-8')
    env = os.environ.copy()
    env['RUSTUP_HOME'] = str(ROOT / 'touchHLE/_build_tools/rustup')
    executable = OUT / 'framebuffer-scale-tests.exe'
    subprocess.run([str(ROOT / 'touchHLE/_build_tools/cargo/bin/rustc.exe'),
                    '--edition=2021', '--test', str(path), '-o', str(executable)],
                   env=env, check=True)
    result = subprocess.run([str(executable), '--test-threads=1'],
                            check=True, capture_output=True, text=True)
    (OUT / 'framebuffer-scale-tests.txt').write_text(result.stdout, encoding='utf-8')
    print(result.stdout)


if __name__ == '__main__':
    main()
