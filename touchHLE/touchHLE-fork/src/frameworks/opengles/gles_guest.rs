/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Wrapper functions exposing OpenGL ES to the guest.
//!
//! This code is intentionally somewhat lax with calculating array sizes when
//! obtainining a pointer with [Mem::ptr_at]. For large chunks of data, e.g. the
//! `pixels` parameter of `glTexImage2D`, it's worth being precise, but for
//! `glFoofv(pname, param)` where `param` is a pointer to one to four `GLfloat`s
//! depending on the value of `pname`, using the upper bound (4 in this case)
//! every time is never going to cause a problem in practice.

use touchHLE_gl_bindings::gles11::{
    ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER_BINDING, VERTEX_ARRAY_BUFFER_BINDING,
    WRITE_ONLY_OES,
};

use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::opengles::eagl::EAGLContextHostObject;
use crate::gles::{gles11_raw as gles11, GLES}; // constants only
use crate::mem::{ConstPtr, ConstVoidPtr, GuestISize, GuestUSize, Mem, MutPtr, MutVoidPtr, Ptr};
use crate::objc::nil;
use crate::Environment;

use std::slice::from_raw_parts;

// These types are the same size in guest code (32-bit) and host code (64-bit).
use crate::gles::gles11_raw::types::{
    GLbitfield, GLboolean, GLclampf, GLclampx, GLenum, GLfixed, GLfloat, GLint, GLsizei, GLubyte,
    GLuint, GLvoid,
};
// These types have different sizes, so some care is needed.
use crate::gles::gles11_raw::types::{GLintptr as HostGLintptr, GLsizeiptr as HostGLsizeiptr};
type GuestGLsizeiptr = GuestISize;
type GuestGLintptr = GuestISize;

/// List of compressed formats supported by our emulation.
/// Currently, it's all the PVRTC and all paletted ones.
const SUPPORTED_COMPRESSED_TEXTURE_FORMATS: &[GLenum] = &[
    // PVRTC
    gles11::COMPRESSED_RGBA_PVRTC_2BPPV1_IMG,
    gles11::COMPRESSED_RGBA_PVRTC_4BPPV1_IMG,
    gles11::COMPRESSED_RGB_PVRTC_2BPPV1_IMG,
    gles11::COMPRESSED_RGB_PVRTC_4BPPV1_IMG,
    // Paletted texture
    gles11::PALETTE4_R5_G6_B5_OES,
    gles11::PALETTE4_RGB5_A1_OES,
    gles11::PALETTE4_RGB8_OES,
    gles11::PALETTE4_RGBA4_OES,
    gles11::PALETTE4_RGBA8_OES,
    gles11::PALETTE8_R5_G6_B5_OES,
    gles11::PALETTE8_RGB5_A1_OES,
    gles11::PALETTE8_RGB8_OES,
    gles11::PALETTE8_RGBA4_OES,
    gles11::PALETTE8_RGBA8_OES,
];

/// Sync the current context and performs a function `f` within it.
///
/// In case of missing EAGL context for a current thread,
/// returns a default value.
/// Opt-in trace of every GL call whose arguments the scale hack rewrites, plus
/// every framebuffer-binding change. Used to answer a specific question: does
/// the app render to its own texture (render-to-texture), and if so, at what
/// size? `--scale-hack` scales the guest's viewport but has no way to know the
/// size of a texture the app allocated itself, so a render-to-texture pass is
/// the one place where scaling can silently change what the app sees.
fn zfr_gl_trace_enabled() -> bool {
    static ENABLED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF_GL_TRACE").ok().as_deref() == Some("1"))
}

/// Trace-only: the framebuffer the guest last bound. Always maintained (not
/// just when tracing), because [zfr_gl_framebuffer_is_scaled] needs it.
static ZFR_GL_CURRENT_FBO: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);

fn zfr_gl_current_framebuffer() -> u32 {
    ZFR_GL_CURRENT_FBO.load(std::sync::atomic::Ordering::Relaxed)
}

/// Per-framebuffer cache of "may the scale hack be applied to this render
/// target?". See [zfr_gl_framebuffer_is_scaled]. Keyed by (context, name),
/// because GL object names are only unique within a context.
static ZFR_GL_FBO_IS_TEXTURE: std::sync::Mutex<
    Option<std::collections::HashMap<(usize, GLuint), bool>>,
> = std::sync::Mutex::new(None);

/// The viewport rectangle exactly as the guest asked for it, in guest pixels.
///
/// GL's viewport is sticky state: it belongs to the context, not to a
/// framebuffer, so an app can set it once and then draw into several different
/// framebuffers. Zombie Farm does exactly that - it sets the viewport while the
/// drawable is bound, then binds its own texture-backed framebuffer and draws
/// without setting a new viewport. To scale that draw correctly we have to know
/// what the guest asked for and re-derive the host rectangle whenever the
/// render target changes.
static ZFR_GL_GUEST_VIEWPORT: std::sync::Mutex<Option<(GLint, GLint, GLsizei, GLsizei)>> =
    std::sync::Mutex::new(None);

fn zfr_gl_set_guest_viewport(x: GLint, y: GLint, width: GLsizei, height: GLsizei) {
    if let Ok(mut guard) = ZFR_GL_GUEST_VIEWPORT.lock() {
        *guard = Some((x, y, width, height));
    }
}

fn zfr_gl_guest_viewport() -> Option<(GLint, GLint, GLsizei, GLsizei)> {
    ZFR_GL_GUEST_VIEWPORT.lock().ok().and_then(|guard| *guard)
}

/// Renderbuffers created by `EAGLContext -renderbufferStorage:fromDrawable:`,
/// i.e. the ones touchHLE itself sized as `logical_size * scale_hack`. These
/// are the only render targets for which the scale hack is sound.
///
/// Keyed by (context, name): GL object names are only unique within a context,
/// and the app creates several contexts.
static ZFR_GL_DRAWABLE_RENDERBUFFERS: std::sync::Mutex<
    Option<std::collections::HashSet<(usize, GLuint)>>,
> = std::sync::Mutex::new(None);

/// Identify the current EAGL context, for namespacing the caches below. Zero
/// means "no context", which is treated as its own namespace.
fn zfr_gl_context_key(env: &mut Environment) -> usize {
    env.framework_state
        .opengles
        .current_ctx_for_thread(env.current_thread)
        .map(|ctx| ctx.to_bits() as usize)
        .unwrap_or(0)
}

/// Called by `eagl.rs` when it creates a drawable-backed renderbuffer.
///
/// The cached per-framebuffer answers are dropped, because a framebuffer may
/// have been queried before its drawable renderbuffer was attached. Without
/// this, an early "not scaled" answer for the drawable could stick and the main
/// screen would stop being scaled at all. Marking happens once per context, so
/// clearing everything is cheap.
pub(super) fn zfr_gl_mark_renderbuffer_drawable_backed(env: &mut Environment, renderbuffer: GLuint) {
    let key = (zfr_gl_context_key(env), renderbuffer);
    if let Ok(mut guard) = ZFR_GL_DRAWABLE_RENDERBUFFERS.lock() {
        guard
            .get_or_insert_with(std::collections::HashSet::new)
            .insert(key);
    }
    if let Ok(mut guard) = ZFR_GL_FBO_IS_TEXTURE.lock() {
        if let Some(map) = guard.as_mut() {
            map.clear();
        }
    }
}

fn zfr_gl_renderbuffer_is_drawable_backed(context: usize, renderbuffer: GLuint) -> bool {
    ZFR_GL_DRAWABLE_RENDERBUFFERS
        .lock()
        .ok()
        .and_then(|guard| {
            guard
                .as_ref()
                .map(|set| set.contains(&(context, renderbuffer)))
        })
        .unwrap_or(false)
}

/// Drop the cached answer for a framebuffer whose attachments just changed.
fn zfr_gl_invalidate_framebuffer_cache(context: usize, fbo: GLuint) {
    if let Ok(mut guard) = ZFR_GL_FBO_IS_TEXTURE.lock() {
        guard
            .get_or_insert_with(std::collections::HashMap::new)
            .remove(&(context, fbo));
    }
}

/// May the scale hack be applied to viewport/scissor coordinates for whichever
/// framebuffer is currently bound?
///
/// The scale hack rests on one assumption: the guest's framebuffer is
/// `logical_size * scale`. That holds for the drawable, because touchHLE
/// allocates its renderbuffer itself at the scaled size. It does *not* hold for
/// a framebuffer the app backed with a texture or renderbuffer of its own:
/// touchHLE cannot make those bigger, so the render target really is
/// guest-sized, and a scaled viewport would draw outside it. The pass then gets
/// clipped, and anything whose position is derived from the viewport rectangle -
/// a glow or light overlay, for instance - no longer lines up with the scene
/// underneath.
///
/// The answer is cached per framebuffer and the cache is dropped whenever an
/// attachment changes, so the GL query runs once per framebuffer rather than
/// once per frame.
fn zfr_gl_framebuffer_is_scaled(gles: &mut dyn GLES, context: usize) -> bool {
    let fbo = zfr_gl_current_framebuffer();
    // The default framebuffer is the window, which touchHLE sizes itself.
    if fbo == 0 {
        return true;
    }
    let key = (context, fbo);
    if let Ok(guard) = ZFR_GL_FBO_IS_TEXTURE.lock() {
        if let Some(&cached) = guard.as_ref().and_then(|map| map.get(&key)) {
            return cached;
        }
    }
    let mut cacheable = true;
    let scaled = unsafe {
        let mut obj_type: GLint = 0;
        let mut obj_name: GLint = 0;
        gles.GetFramebufferAttachmentParameterivOES(
            gles11::FRAMEBUFFER_OES,
            gles11::COLOR_ATTACHMENT0_OES,
            0x8cd0, // GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE_OES
            &mut obj_type,
        );
        gles.GetFramebufferAttachmentParameterivOES(
            gles11::FRAMEBUFFER_OES,
            gles11::COLOR_ATTACHMENT0_OES,
            0x8cd1, // GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME_OES
            &mut obj_name,
        );
        if obj_type == 0x8d41 {
            // GL_RENDERBUFFER_OES: only a drawable-backed one is scaled.
            zfr_gl_renderbuffer_is_drawable_backed(context, obj_name as GLuint)
        } else if obj_type == 0x1702 {
            // GL_TEXTURE: an app-owned texture, which we cannot enlarge.
            false
        } else {
            // No colour attachment yet. The framebuffer is incomplete, so this
            // answer is provisional - do not cache it, or a later attach would
            // never be noticed.
            cacheable = false;
            false
        }
    };
    if cacheable {
        if let Ok(mut guard) = ZFR_GL_FBO_IS_TEXTURE.lock() {
            guard
                .get_or_insert_with(std::collections::HashMap::new)
                .insert(key, scaled);
        }
    }
    if !scaled && zfr_gl_trace_enabled() {
        log!(
            "ZFR GL trace: fbo {} is app-owned; NOT scaling its viewport/scissor",
            fbo
        );
    }
    scaled
}

/// Trace-only: the texture bound to GL_TEXTURE_2D, and the size every texture
/// was last allocated at. Needed to answer one question: when the app attaches
/// a texture to its own framebuffer, is that texture big enough for the
/// viewport touchHLE scales up? touchHLE scales the drawable renderbuffer but
/// cannot scale a texture the app allocated, so a pass into an app-owned
/// texture would be clipped by the scale factor.
static ZFR_GL_TRACE_TEXTURE: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
static ZFR_GL_TRACE_TEXTURE_SIZES: std::sync::Mutex<
    Option<std::collections::HashMap<GLuint, (GLsizei, GLsizei)>>,
> = std::sync::Mutex::new(None);

fn zfr_gl_trace_record_texture(texture: GLuint, width: GLsizei, height: GLsizei) {
    if let Ok(mut guard) = ZFR_GL_TRACE_TEXTURE_SIZES.lock() {
        guard
            .get_or_insert_with(std::collections::HashMap::new)
            .insert(texture, (width, height));
    }
}

fn zfr_gl_trace_texture_size(texture: GLuint) -> Option<(GLsizei, GLsizei)> {
    ZFR_GL_TRACE_TEXTURE_SIZES
        .lock()
        .ok()
        .and_then(|guard| guard.as_ref().and_then(|map| map.get(&texture).copied()))
}

/// Trace-only: the last host viewport handed to GL, so a draw call can report
/// the rectangle it is about to render into.
static ZFR_GL_TRACE_VIEWPORT: std::sync::atomic::AtomicI64 = std::sync::atomic::AtomicI64::new(0);

fn zfr_gl_trace_set_viewport(x: i32, y: i32, width: i32, height: i32) {
    let packed = ((width as i64) << 32) | (height as i64 & 0xffff_ffff);
    let _ = (x, y);
    ZFR_GL_TRACE_VIEWPORT.store(packed, std::sync::atomic::Ordering::Relaxed);
}

fn zfr_gl_trace_viewport() -> (i32, i32) {
    let packed = ZFR_GL_TRACE_VIEWPORT.load(std::sync::atomic::Ordering::Relaxed);
    ((packed >> 32) as i32, (packed & 0xffff_ffff) as i32)
}

fn with_ctx_and_mem<T, U: Default>(env: &mut Environment, f: T) -> U
where
    T: FnOnce(&mut dyn GLES, &mut Mem) -> U,
{
    if env
        .framework_state
        .opengles
        .current_ctx_for_thread(env.current_thread)
        .is_none()
    {
        log!(
            "Warning: No EAGLContext for thread {}! Ignoring OpenGL ES call, returning default value.",
            env.current_thread
        );
        return U::default();
    }

    let mut gles = super::sync_context(
        &mut env.framework_state.opengles,
        &mut env.objc,
        env.window
            .as_mut()
            .expect("OpenGL ES is not supported in headless mode"),
        env.current_thread,
    );

    //panic_on_gl_errors(&mut *gles);
    let res = f(gles.as_mut(), &mut env.mem);
    //panic_on_gl_errors(&mut *gles);
    #[allow(clippy::let_and_return)]
    res
}

/// Version of with_ctx_and_mem which panics on a missing context.
///
/// Needed because for return types such as `*mut GLvoid` we cannnot
/// return a default value in case EAGL context is missing for
/// a current thread.
fn with_ctx_and_mem_no_skip<T, U>(env: &mut Environment, f: T) -> U
where
    T: FnOnce(&mut dyn GLES, &mut Mem) -> U,
{
    let mut gles = super::sync_context(
        &mut env.framework_state.opengles,
        &mut env.objc,
        env.window
            .as_mut()
            .expect("OpenGL ES is not supported in headless mode"),
        env.current_thread,
    );

    //panic_on_gl_errors(&mut **gles);
    let res = f(gles.as_mut(), &mut env.mem);
    //panic_on_gl_errors(&mut **gles);
    #[allow(clippy::let_and_return)]
    res
}

/// Useful for debugging
#[allow(dead_code)]
fn panic_on_gl_errors(gles: &mut dyn GLES) {
    let mut did_error = false;
    loop {
        let err = unsafe { gles.GetError() };
        if err == 0 {
            break;
        }
        did_error = true;
        echo!("glGetError() => {:#x}", err);
    }
    if did_error {
        panic!();
    }
}

// Generic state manipulation
fn glGetError(env: &mut Environment) -> GLenum {
    let ignore_gl_errors = env.options.ignore_gl_errors;
    with_ctx_and_mem(env, |gles, _mem| {
        let err = unsafe { gles.GetError() };
        if err != 0 {
            if ignore_gl_errors {
                log_once!(
                    "Warning: Guest error reporting is ignored for glGetError(), returning 0."
                );
                return 0;
            }
            log!("Warning: glGetError() returned {:#x}", err);
        }
        err
    })
}
fn glEnable(env: &mut Environment, cap: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Enable(cap) };
    });
}
fn glIsEnabled(env: &mut Environment, cap: GLenum) -> GLboolean {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.IsEnabled(cap) })
}
fn glDisable(env: &mut Environment, cap: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Disable(cap) };
    });
}
fn glClientActiveTexture(env: &mut Environment, texture: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.ClientActiveTexture(texture)
    })
}
fn glEnableClientState(env: &mut Environment, array: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.EnableClientState(array) };
    });
}
fn glDisableClientState(env: &mut Environment, array: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.DisableClientState(array) };
    });
}
fn glGetBooleanv(env: &mut Environment, pname: GLenum, params: MutPtr<GLboolean>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 16 /* upper bound */);
        unsafe { gles.GetBooleanv(pname, params) };
    });
}
fn glGetFloatv(env: &mut Environment, pname: GLenum, params: MutPtr<GLfloat>) {
    assert_ne!(gles11::NUM_COMPRESSED_TEXTURE_FORMATS, pname);
    assert_ne!(gles11::COMPRESSED_TEXTURE_FORMATS, pname);
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 16 /* upper bound */);
        unsafe { gles.GetFloatv(pname, params) };
    });
}
fn glGetIntegerv(env: &mut Environment, pname: GLenum, params: MutPtr<GLint>) {
    if zfr_gl_trace_enabled() {
        // The scale hack rewrites the viewport, the scissor box and the
        // renderbuffer size on the way out, and un-scales the renderbuffer size
        // on the way back. Every other query falls through to the host
        // unmodified, so these pnames are exactly the ones where the app could
        // observe a number that does not match its own idea of the screen.
        match pname {
            0x0ba2 => {
                log!("ZFR GL trace: glGetIntegerv(GL_VIEWPORT) - falls through to host!");
            }
            0x0c10 => {
                log!("ZFR GL trace: glGetIntegerv(GL_SCISSOR_BOX) - falls through to host!");
            }
            0x0d3a => {
                log!("ZFR GL trace: glGetIntegerv(GL_MAX_VIEWPORT_DIMS)");
            }
            0x8d42 | 0x8d43 => {
                log!("ZFR GL trace: glGetIntegerv(renderbuffer size {:#x})", pname);
            }
            _ => {}
        }
    }
    with_ctx_and_mem(env, |gles, mem| {
        match pname {
            gles11::NUM_COMPRESSED_TEXTURE_FORMATS => {
                mem.write(params, SUPPORTED_COMPRESSED_TEXTURE_FORMATS.len() as _);
            }
            gles11::COMPRESSED_TEXTURE_FORMATS => {
                for (idx, &format) in SUPPORTED_COMPRESSED_TEXTURE_FORMATS.iter().enumerate() {
                    mem.write(params + idx as GuestUSize, format as _);
                }
            }
            // MAX_COLOR_ATTACHMENTS_EXT or MAX_COLOR_ATTACHMENTS_OES
            0x8cdf => {
                // According to [OES_framebuffer_object](https://registry.khronos.org/OpenGL/extensions/OES/OES_framebuffer_object.txt),
                // MAX_COLOR_ATTACHMENTS_OES is not supported in the extension,
                // but we return 1 to match the real device.
                mem.write(params, 1 as _);
            }
            // MAX_SAMPLES or MAX_SAMPLES_ANGLE
            0x8d57 => {
                // TODO: handle GetBooleanv and GetFloatv as well
                // 1 is an initial value
                // TODO: This is an OpenGL ES 2.0 extension, not supported yet
                mem.write(params, 1 as _);
            }
            _ => {
                let params = mem.ptr_at_mut(params, 16 /* upper bound */);
                unsafe { gles.GetIntegerv(pname, params) };
            }
        }
    });
}
fn glGetPointerv(env: &mut Environment, pname: GLenum, params: MutPtr<ConstVoidPtr>) {
    use crate::gles::gles1_on_gl2::{ArrayInfo, ARRAYS};
    let &ArrayInfo { buffer_binding, .. } =
        ARRAYS.iter().find(|info| info.pointer == pname).unwrap();
    with_ctx_and_mem(env, |gles, mem| {
        // params always points to just one pointer for this function
        let mut host_pointer_or_offset = std::ptr::null();
        let guest_pointer_or_offset = unsafe {
            gles.GetPointerv(pname, &mut host_pointer_or_offset);
            translate_pointer_or_offset_to_guest(gles, mem, host_pointer_or_offset, buffer_binding)
        };
        mem.write(params, guest_pointer_or_offset);
    });
}
fn glGetTexEnviv(env: &mut Environment, target: GLenum, pname: GLenum, params: MutPtr<GLint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 16 /* upper bound */);
        unsafe { gles.GetTexEnviv(target, pname, params) };
    });
}
fn glGetTexEnvfv(env: &mut Environment, target: GLenum, pname: GLenum, params: MutPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 16 /* upper bound */);
        unsafe { gles.GetTexEnvfv(target, pname, params) };
    });
}

fn glHint(env: &mut Environment, target: GLenum, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Hint(target, mode) })
}
fn glFinish(env: &mut Environment) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Finish() })
}
fn glFlush(env: &mut Environment) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Flush() })
}
fn glGetString(env: &mut Environment, name: GLenum) -> ConstPtr<GLubyte> {
    let res = if let Some(&str) = env.framework_state.opengles.strings_cache.get(&name) {
        str
    } else {
        let new_str = with_ctx_and_mem(env, |_gles, mem| {
            // Those values are extracted from the iPod touch 2nd gen, iOS 4.2.1
            let s: &[u8] = match name {
                gles11::VENDOR => {
                    b"Imagination Technologies"
                }
                gles11::RENDERER => {
                    b"PowerVR MBXLite with VGPLite"
                }
                gles11::VERSION => {
                    b"OpenGL ES-CM 1.1 (76)"
                }
                gles11::EXTENSIONS => {
                    b"GL_APPLE_framebuffer_multisample GL_APPLE_texture_max_level GL_EXT_discard_framebuffer GL_EXT_texture_filter_anisotropic GL_EXT_texture_lod_bias GL_IMG_read_format GL_IMG_texture_compression_pvrtc GL_IMG_texture_format_BGRA8888 GL_OES_blend_subtract GL_OES_compressed_paletted_texture GL_OES_depth24 GL_OES_draw_texture GL_OES_framebuffer_object GL_OES_mapbuffer GL_OES_matrix_palette GL_OES_point_size_array GL_OES_point_sprite GL_OES_read_format GL_OES_rgb8_rgba8 GL_OES_texture_mirrored_repeat GL_OES_vertex_array_object "
                }
                _ => unreachable!(),
            };
            mem.alloc_and_write_cstr(s).cast_const()
        });
        env.framework_state
            .opengles
            .strings_cache
            .insert(name, new_str);
        new_str
    };
    log_dbg!("glGetString({}) => {:?}", name, res);
    res
}

// Other state manipulation
fn glAlphaFunc(env: &mut Environment, func: GLenum, ref_: GLclampf) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.AlphaFunc(func, ref_) })
}
fn glAlphaFuncx(env: &mut Environment, func: GLenum, ref_: GLclampx) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.AlphaFuncx(func, ref_) })
}
fn glBlendFunc(env: &mut Environment, sfactor: GLenum, dfactor: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.BlendFunc(sfactor, dfactor)
    })
}
fn glBlendEquationOES(env: &mut Environment, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.BlendEquationOES(mode) })
}
fn glColorMask(
    env: &mut Environment,
    red: GLboolean,
    green: GLboolean,
    blue: GLboolean,
    alpha: GLboolean,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.ColorMask(red, green, blue, alpha)
    })
}
fn glClipPlanef(env: &mut Environment, plane: GLenum, equation: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let equation = mem.ptr_at(equation, 4 /* upper bound */);
        unsafe { gles.ClipPlanef(plane, equation) }
    })
}
fn glClipPlanex(env: &mut Environment, plane: GLenum, equation: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let equation = mem.ptr_at(equation, 4 /* upper bound */);
        unsafe { gles.ClipPlanex(plane, equation) }
    })
}
fn glCullFace(env: &mut Environment, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.CullFace(mode) })
}
fn glDepthFunc(env: &mut Environment, func: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.DepthFunc(func) })
}
fn glDepthMask(env: &mut Environment, flag: GLboolean) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.DepthMask(flag) })
}
fn glDepthRangef(env: &mut Environment, near: GLclampf, far: GLclampf) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.DepthRangef(near, far) })
}
fn glDepthRangex(env: &mut Environment, near: GLclampx, far: GLclampx) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.DepthRangex(near, far) })
}
fn glFrontFace(env: &mut Environment, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.FrontFace(mode) })
}
fn glPolygonOffset(env: &mut Environment, factor: GLfloat, units: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.PolygonOffset(factor, units)
    })
}
fn glPolygonOffsetx(env: &mut Environment, factor: GLfixed, units: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.PolygonOffsetx(factor, units)
    })
}
fn glSampleCoverage(env: &mut Environment, value: GLclampf, invert: GLboolean) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.SampleCoverage(value, invert)
    })
}
fn glSampleCoveragex(env: &mut Environment, value: GLclampx, invert: GLboolean) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.SampleCoveragex(value, invert)
    })
}
fn glShadeModel(env: &mut Environment, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.ShadeModel(mode) })
}
fn glScissor(env: &mut Environment, x: GLint, y: GLint, width: GLsizei, height: GLsizei) {
    // apply scale hack: assume framebuffer's size is larger than the app thinks
    // and scale scissor appropriately. Like the viewport, this is only valid
    // for a framebuffer touchHLE sized itself; for an app-owned render target
    // the coordinates are already true pixels.
    let (num, den) = (
        env.options.scale_hack.get(),
        env.options.scale_hack_den.get(),
    );
    let (mut x, mut y) = (x, y);
    let (mut width, mut height) = (width, height);
    let scaled = zfr_gl_current_framebuffer() == 0 || {
        let context = zfr_gl_context_key(env);
        with_ctx_and_mem(env, |gles, _mem| {
            zfr_gl_framebuffer_is_scaled(gles, context)
        })
    };
    if scaled {
        x = crate::options::scale_dim_i(x, num, den);
        y = crate::options::scale_dim_i(y, num, den);
        width = crate::options::scale_dim_i(width, num, den);
        height = crate::options::scale_dim_i(height, num, den);
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Scissor(x, y, width, height)
    })
}
fn glViewport(env: &mut Environment, x: GLint, y: GLint, width: GLsizei, height: GLsizei) {
    // Remember what the guest asked for; the host rectangle depends on which
    // render target is bound, and may need recomputing when that changes.
    zfr_gl_set_guest_viewport(x, y, width, height);
    apply_guest_viewport(env, "glViewport");
}
/// Push the guest's requested viewport to GL, scaled or not depending on
/// whether the currently bound render target is one touchHLE sized itself.
///
/// `origin` only labels the trace output. Called both from `glViewport` and
/// whenever the bound framebuffer changes, because GL's viewport is sticky
/// context state while the correct scaling depends on the render target.
fn apply_guest_viewport(env: &mut Environment, origin: &str) {
    let Some((gx, gy, gw, gh)) = zfr_gl_guest_viewport() else {
        return;
    };
    let (num, den) = (
        env.options.scale_hack.get(),
        env.options.scale_hack_den.get(),
    );
    // The default framebuffer is the window, which touchHLE sized itself, so it
    // is scaled even before any context exists. Going through the GL query for
    // it would return the "no context" default of false and lose the scale.
    let scaled = zfr_gl_current_framebuffer() == 0 || {
        let context = zfr_gl_context_key(env);
        with_ctx_and_mem(env, |gles, _mem| {
            zfr_gl_framebuffer_is_scaled(gles, context)
        })
    };
    let (x, y, width, height) = if scaled {
        (
            crate::options::scale_dim_i(gx, num, den),
            crate::options::scale_dim_i(gy, num, den),
            crate::options::scale_dim_i(gw, num, den),
            crate::options::scale_dim_i(gh, num, den),
        )
    } else {
        (gx, gy, gw, gh)
    };
    if zfr_gl_trace_enabled() {
        zfr_gl_trace_set_viewport(x, y, width, height);
        log!(
            "ZFR GL trace: {}: guest {},{},{},{} -> host {},{},{},{} [fbo {}, scaled {}]",
            origin,
            gx,
            gy,
            gw,
            gh,
            x,
            y,
            width,
            height,
            zfr_gl_current_framebuffer(),
            scaled
        );
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Viewport(x, y, width, height)
    });
}

fn glLineWidth(env: &mut Environment, val: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.LineWidth(val) })
}
fn glLineWidthx(env: &mut Environment, val: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.LineWidthx(val) })
}
fn glStencilFunc(env: &mut Environment, func: GLenum, ref_: GLint, mask: GLuint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.StencilFunc(func, ref_, mask)
    });
}
fn glStencilOp(env: &mut Environment, sfail: GLenum, dpfail: GLenum, dppass: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.StencilOp(sfail, dpfail, dppass)
    });
}
fn glStencilMask(env: &mut Environment, mask: GLuint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.StencilMask(mask) });
}
fn glLogicOp(env: &mut Environment, opcode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.LogicOp(opcode) });
}
// Points
fn glPointSize(env: &mut Environment, size: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.PointSize(size) })
}
fn glPointSizex(env: &mut Environment, size: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.PointSizex(size) })
}
fn glPointParameterf(env: &mut Environment, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.PointParameterf(pname, param)
    })
}
fn glPointParameterx(env: &mut Environment, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.PointParameterx(pname, param)
    })
}
fn glPointParameterfv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.PointParameterfv(pname, params) }
    })
}
fn glPointParameterxv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.PointParameterxv(pname, params) }
    })
}

// Lighting and materials
fn glFogf(env: &mut Environment, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Fogf(pname, param) })
}
fn glFogx(env: &mut Environment, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Fogx(pname, param) })
}
fn glFogfv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Fogfv(pname, params) }
    })
}
fn glFogxv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Fogxv(pname, params) }
    })
}
fn glLightf(env: &mut Environment, light: GLenum, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Lightf(light, pname, param)
    })
}
fn glLightx(env: &mut Environment, light: GLenum, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Lightx(light, pname, param)
    })
}
fn glLightfv(env: &mut Environment, light: GLenum, pname: GLenum, params: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Lightfv(light, pname, params) }
    })
}
fn glLightxv(env: &mut Environment, light: GLenum, pname: GLenum, params: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Lightxv(light, pname, params) }
    })
}
fn glLightModelf(env: &mut Environment, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.LightModelf(pname, param) })
}
fn glLightModelx(env: &mut Environment, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.LightModelx(pname, param) })
}
fn glLightModelfv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.LightModelfv(pname, params) }
    })
}
fn glLightModelxv(env: &mut Environment, pname: GLenum, params: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.LightModelxv(pname, params) }
    })
}
fn glMaterialf(env: &mut Environment, face: GLenum, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Materialf(face, pname, param)
    })
}
fn glMaterialx(env: &mut Environment, face: GLenum, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Materialx(face, pname, param)
    })
}
fn glMaterialfv(env: &mut Environment, face: GLenum, pname: GLenum, params: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Materialfv(face, pname, params) }
    })
}
fn glMaterialxv(env: &mut Environment, face: GLenum, pname: GLenum, params: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.Materialxv(face, pname, params) }
    })
}

// Buffers
fn glIsBuffer(env: &mut Environment, buffer: GLuint) -> GLboolean {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.IsBuffer(buffer) })
}
fn glGenBuffers(env: &mut Environment, n: GLsizei, buffers: MutPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let buffers = mem.ptr_at_mut(buffers, n_usize);
        unsafe { gles.GenBuffers(n, buffers) }
    })
}
fn glDeleteBuffers(env: &mut Environment, n: GLsizei, buffers: ConstPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let buffers = mem.ptr_at(buffers, n_usize);
        unsafe { gles.DeleteBuffers(n, buffers) }
    })
}
fn glBindBuffer(env: &mut Environment, target: GLenum, buffer: GLuint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.BindBuffer(target, buffer) })
}
fn glBufferData(
    env: &mut Environment,
    target: GLenum,
    size: GuestGLsizeiptr,
    data: ConstPtr<GLvoid>,
    usage: GLenum,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let data = if data.is_null() {
            std::ptr::null()
        } else {
            mem.ptr_at(data.cast::<u8>(), size.try_into().unwrap())
                .cast()
        };
        gles.BufferData(target, size as HostGLsizeiptr, data, usage)
    })
}

fn glBufferSubData(
    env: &mut Environment,
    target: GLenum,
    offset: GuestGLintptr,
    size: GuestGLsizeiptr,
    data: ConstPtr<GLvoid>,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let data = if data.is_null() {
            std::ptr::null()
        } else {
            mem.ptr_at(data.cast::<u8>(), size.try_into().unwrap())
                .cast()
        };
        gles.BufferSubData(target, offset as HostGLintptr, size as HostGLsizeiptr, data)
    })
}

// Non-pointers
fn glColor4f(env: &mut Environment, red: GLfloat, green: GLfloat, blue: GLfloat, alpha: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Color4f(red, green, blue, alpha)
    })
}
fn glColor4x(env: &mut Environment, red: GLfixed, green: GLfixed, blue: GLfixed, alpha: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Color4x(red, green, blue, alpha)
    })
}
fn glColor4ub(env: &mut Environment, red: GLubyte, green: GLubyte, blue: GLubyte, alpha: GLubyte) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.Color4ub(red, green, blue, alpha)
    })
}
fn glNormal3f(env: &mut Environment, nx: GLfloat, ny: GLfloat, nz: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Normal3f(nx, ny, nz) })
}
fn glNormal3x(env: &mut Environment, nx: GLfixed, ny: GLfixed, nz: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Normal3x(nx, ny, nz) })
}

// Pointers

/// Helper for implementing OpenGL pointer setting functions.
///
/// One of the ugliest things in OpenGL is that, depending on dynamic state
/// (`ARRAY_BUFFER_BINDING` or `ELEMENT_ARRAY_BUFFER_BINDING`), the pointer
/// parameter of certain functions is either a pointer or an offset!
///
/// See also: [translate_pointer_or_offset_to_guest]
unsafe fn translate_pointer_or_offset_to_host(
    gles: &mut dyn GLES,
    mem: &Mem,
    pointer_or_offset: ConstVoidPtr,
    which_binding: GLenum,
) -> *const GLvoid {
    let mut buffer_binding = 0;
    gles.GetIntegerv(which_binding, &mut buffer_binding);
    if buffer_binding != 0 {
        let offset = pointer_or_offset.to_bits();
        offset as usize as *const _
    } else if pointer_or_offset.is_null() {
        std::ptr::null()
    } else {
        let pointer = pointer_or_offset;
        // We need to use an unchecked version of ptr_at to avoid crashing here
        // if dynamic state was disabled.
        // Also, bounds checking is hopeless here
        mem.unchecked_ptr_at(pointer.cast::<u8>(), 0)
            .cast::<GLvoid>()
    }
}

/// Helper for implementing OpenGL pointer retrieval.
///
/// Reverse of [translate_pointer_or_offset_to_host]. Depending on the value
/// of `VERTEX_ARRAY_BUFFER_BINDING`/`NORMAL_ARRAY_BUFFER_BINDING`/etc
/// (not to be confused with `ARRAY_BUFFER_BINDING`, only used when *setting*),
/// the pointer retrieved with `glGetPointerv` may actually be an offset.
///
/// See also: [translate_pointer_or_offset_to_host]
unsafe fn translate_pointer_or_offset_to_guest(
    gles: &mut dyn GLES,
    mem: &Mem,
    pointer_or_offset: *const GLvoid,
    which_binding: GLenum,
) -> ConstVoidPtr {
    let mut buffer_binding = 0;
    gles.GetIntegerv(which_binding, &mut buffer_binding);
    if buffer_binding != 0 {
        let offset = pointer_or_offset as usize;
        Ptr::from_bits(u32::try_from(offset).unwrap())
    } else if pointer_or_offset.is_null() {
        Ptr::null()
    } else {
        let pointer = pointer_or_offset;
        mem.host_ptr_to_guest_ptr(pointer)
    }
}

fn glColorPointer(
    env: &mut Environment,
    size: GLint,
    type_: GLenum,
    stride: GLsizei,
    pointer: ConstVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pointer =
            translate_pointer_or_offset_to_host(gles, mem, pointer, gles11::ARRAY_BUFFER_BINDING);
        gles.ColorPointer(size, type_, stride, pointer)
    })
}
fn glNormalPointer(env: &mut Environment, type_: GLenum, stride: GLsizei, pointer: ConstVoidPtr) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pointer =
            translate_pointer_or_offset_to_host(gles, mem, pointer, gles11::ARRAY_BUFFER_BINDING);
        gles.NormalPointer(type_, stride, pointer)
    })
}
fn glTexCoordPointer(
    env: &mut Environment,
    size: GLint,
    type_: GLenum,
    stride: GLsizei,
    pointer: ConstVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pointer =
            translate_pointer_or_offset_to_host(gles, mem, pointer, gles11::ARRAY_BUFFER_BINDING);
        gles.TexCoordPointer(size, type_, stride, pointer)
    })
}
fn glVertexPointer(
    env: &mut Environment,
    size: GLint,
    type_: GLenum,
    stride: GLsizei,
    pointer: ConstVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pointer =
            translate_pointer_or_offset_to_host(gles, mem, pointer, gles11::ARRAY_BUFFER_BINDING);
        gles.VertexPointer(size, type_, stride, pointer)
    })
}

// Drawing
fn glDrawArrays(env: &mut Environment, mode: GLenum, first: GLint, count: GLsizei) {
    if zfr_gl_trace_enabled() {
        let (vw, vh) = zfr_gl_trace_viewport();
        let fbo = zfr_gl_current_framebuffer();
        // Only the interesting case: drawing into a framebuffer that is not the
        // real screen, at a viewport touchHLE has scaled up. If the framebuffer
        // is backed by an app texture, that rectangle is bigger than the
        // texture, so the scene is clipped or the glow lands in the wrong place.
        if fbo != 0 {
            log!(
                "ZFR GL trace: DRAW into fbo {} with viewport {}x{}, mode {:#x}, count {}",
                fbo,
                vw,
                vh,
                mode,
                count
            );
        }
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        let fog_state_backup = clamp_fog_state_values(gles);
        gles.DrawArrays(mode, first, count);
        restore_fog_state_values(gles, fog_state_backup);
    })
}
fn glDrawElements(
    env: &mut Environment,
    mode: GLenum,
    count: GLsizei,
    type_: GLenum,
    indices: ConstVoidPtr,
) {
    if zfr_gl_trace_enabled() {
        let (vw, vh) = zfr_gl_trace_viewport();
        let fbo = zfr_gl_current_framebuffer();
        if fbo != 0 {
            log!(
                "ZFR GL trace: DRAW into fbo {} with viewport {}x{}, mode {:#x}, count {}",
                fbo,
                vw,
                vh,
                mode,
                count
            );
        }
    }
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let fog_state_backup = clamp_fog_state_values(gles);
        let indices = translate_pointer_or_offset_to_host(
            gles,
            mem,
            indices,
            gles11::ELEMENT_ARRAY_BUFFER_BINDING,
        );
        gles.DrawElements(mode, count, type_, indices);
        restore_fog_state_values(gles, fog_state_backup);
    })
}

// Clearing
fn glClear(env: &mut Environment, mask: GLbitfield) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.Clear(mask) });
}
fn glClearColor(
    env: &mut Environment,
    red: GLclampf,
    green: GLclampf,
    blue: GLclampf,
    alpha: GLclampf,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.ClearColor(red, green, blue, alpha)
    });
}
fn glClearColorx(
    env: &mut Environment,
    red: GLclampx,
    green: GLclampx,
    blue: GLclampx,
    alpha: GLclampx,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.ClearColorx(red, green, blue, alpha)
    });
}
fn glClearDepthf(env: &mut Environment, depth: GLclampf) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.ClearDepthf(depth) });
}
fn glClearDepthx(env: &mut Environment, depth: GLclampx) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.ClearDepthx(depth) });
}
fn glClearStencil(env: &mut Environment, s: GLint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.ClearStencil(s) });
}

// Matrix stack operations
fn glMatrixMode(env: &mut Environment, mode: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.MatrixMode(mode) };
    });
}
fn glLoadIdentity(env: &mut Environment) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.LoadIdentity() };
    });
}
fn glLoadMatrixf(env: &mut Environment, m: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let m = mem.ptr_at(m, 16);
        unsafe { gles.LoadMatrixf(m) };
    });
}
fn glLoadMatrixx(env: &mut Environment, m: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let m = mem.ptr_at(m, 16);
        unsafe { gles.LoadMatrixx(m) };
    });
}
fn glMultMatrixf(env: &mut Environment, m: ConstPtr<GLfloat>) {
    with_ctx_and_mem(env, |gles, mem| {
        let m = mem.ptr_at(m, 16);
        unsafe { gles.MultMatrixf(m) };
    });
}
fn glMultMatrixx(env: &mut Environment, m: ConstPtr<GLfixed>) {
    with_ctx_and_mem(env, |gles, mem| {
        let m = mem.ptr_at(m, 16);
        unsafe { gles.MultMatrixx(m) };
    });
}
fn glPushMatrix(env: &mut Environment) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.PushMatrix() };
    });
}
fn glPopMatrix(env: &mut Environment) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.PopMatrix() };
    });
}
fn glOrthof(
    env: &mut Environment,
    left: GLfloat,
    right: GLfloat,
    bottom: GLfloat,
    top: GLfloat,
    near: GLfloat,
    far: GLfloat,
) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Orthof(left, right, bottom, top, near, far) };
    });
}
fn glOrthox(
    env: &mut Environment,
    left: GLfixed,
    right: GLfixed,
    bottom: GLfixed,
    top: GLfixed,
    near: GLfixed,
    far: GLfixed,
) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Orthox(left, right, bottom, top, near, far) };
    });
}
fn glFrustumf(
    env: &mut Environment,
    left: GLfloat,
    right: GLfloat,
    bottom: GLfloat,
    top: GLfloat,
    near: GLfloat,
    far: GLfloat,
) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Frustumf(left, right, bottom, top, near, far) };
    });
}
fn glFrustumx(
    env: &mut Environment,
    left: GLfixed,
    right: GLfixed,
    bottom: GLfixed,
    top: GLfixed,
    near: GLfixed,
    far: GLfixed,
) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Frustumx(left, right, bottom, top, near, far) };
    });
}
fn glRotatef(env: &mut Environment, angle: GLfloat, x: GLfloat, y: GLfloat, z: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Rotatef(angle, x, y, z) };
    });
}
fn glRotatex(env: &mut Environment, angle: GLfixed, x: GLfixed, y: GLfixed, z: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Rotatex(angle, x, y, z) };
    });
}
fn glScalef(env: &mut Environment, x: GLfloat, y: GLfloat, z: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Scalef(x, y, z) };
    });
}
fn glScalex(env: &mut Environment, x: GLfixed, y: GLfixed, z: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Scalex(x, y, z) };
    });
}
fn glTranslatef(env: &mut Environment, x: GLfloat, y: GLfloat, z: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Translatef(x, y, z) };
    });
}
fn glTranslatex(env: &mut Environment, x: GLfixed, y: GLfixed, z: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| {
        unsafe { gles.Translatex(x, y, z) };
    });
}

// Textures
fn glPixelStorei(env: &mut Environment, pname: GLenum, param: GLint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.PixelStorei(pname, param) })
}
fn glReadPixels(
    env: &mut Environment,
    x: GLint,
    y: GLint,
    width: GLsizei,
    height: GLsizei,
    format: GLenum,
    type_: GLenum,
    pixels: MutVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| {
        let pixels = {
            let pixel_count: GuestUSize = width.checked_mul(height).unwrap().try_into().unwrap();
            let size = image_size_estimate(pixel_count, format, type_);
            mem.ptr_at_mut(pixels.cast::<u8>(), size).cast::<GLvoid>()
        };
        unsafe { gles.ReadPixels(x, y, width, height, format, type_, pixels) }
    })
}
fn glGenTextures(env: &mut Environment, n: GLsizei, textures: MutPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let textures = mem.ptr_at_mut(textures, n_usize);
        unsafe { gles.GenTextures(n, textures) }
    })
}
fn glDeleteTextures(env: &mut Environment, n: GLsizei, textures: ConstPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let textures = mem.ptr_at(textures, n_usize);
        unsafe { gles.DeleteTextures(n, textures) }
    })
}
fn glActiveTexture(env: &mut Environment, texture: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.ActiveTexture(texture) })
}
fn glIsTexture(env: &mut Environment, texture: GLuint) -> GLboolean {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.IsTexture(texture) })
}
fn glBindTexture(env: &mut Environment, target: GLenum, texture: GLuint) {
    if zfr_gl_trace_enabled() {
        ZFR_GL_TRACE_TEXTURE.store(texture, std::sync::atomic::Ordering::Relaxed);
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.BindTexture(target, texture)
    })
}
fn glTexParameteri(env: &mut Environment, target: GLenum, pname: GLenum, param: GLint) {
    // So long as we haven't implemented glDrawTexOES yet, we can just ignore
    // this parameter, because it doesn't do anything for normal texture use.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexParameteri(target, pname, param)
    })
}
fn glTexParameterf(env: &mut Environment, target: GLenum, pname: GLenum, param: GLfloat) {
    // See above.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexParameterf(target, pname, param)
    })
}
fn glTexParameterx(env: &mut Environment, target: GLenum, pname: GLenum, param: GLfixed) {
    // See above.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexParameterx(target, pname, param)
    })
}
fn glTexParameteriv(env: &mut Environment, target: GLenum, pname: GLenum, params: ConstPtr<GLint>) {
    // See above.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let params = mem.ptr_at(params, 1 /* upper bound */);
        gles.TexParameteriv(target, pname, params)
    })
}
fn glTexParameterfv(
    env: &mut Environment,
    target: GLenum,
    pname: GLenum,
    params: ConstPtr<GLfloat>,
) {
    // See above.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let params = mem.ptr_at(params, 1 /* upper bound */);
        gles.TexParameterfv(target, pname, params)
    })
}
fn glTexParameterxv(
    env: &mut Environment,
    target: GLenum,
    pname: GLenum,
    params: ConstPtr<GLfixed>,
) {
    // See above.
    if pname == gles11::TEXTURE_CROP_RECT_OES {
        return;
    }
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let params = mem.ptr_at(params, 1 /* upper bound */);
        gles.TexParameterxv(target, pname, params)
    })
}
fn image_size_estimate(pixel_count: GuestUSize, format: GLenum, type_: GLenum) -> GuestUSize {
    let bytes_per_pixel: GuestUSize = match type_ {
        gles11::UNSIGNED_BYTE => match format {
            gles11::ALPHA | gles11::LUMINANCE => 1,
            gles11::LUMINANCE_ALPHA => 2,
            gles11::RGB => 3,
            gles11::RGBA => 4,
            gles11::BGRA_EXT => 4,
            _ => panic!("Unexpected format {format:#x}"),
        },
        gles11::UNSIGNED_SHORT_5_6_5
        | gles11::UNSIGNED_SHORT_4_4_4_4
        | gles11::UNSIGNED_SHORT_5_5_5_1 => 2,
        _ => panic!("Unexpected type {type_:#x}"),
    };
    // This is approximate, it doesn't account for alignment.
    pixel_count.checked_mul(bytes_per_pixel).unwrap()
}
fn glTexImage2D(
    env: &mut Environment,
    target: GLenum,
    level: GLint,
    internalformat: GLint,
    width: GLsizei,
    height: GLsizei,
    border: GLint,
    format: GLenum,
    type_: GLenum,
    pixels: ConstVoidPtr,
) {
    let null_data = pixels.is_null();
    if zfr_gl_trace_enabled() {
        // Every texture allocation, with its size. touchHLE scales the
        // drawable renderbuffer but has no way to scale a texture the app
        // allocates; if the app renders into one of these at a scaled viewport,
        // the pass is clipped or stretched.
        let bound = ZFR_GL_TRACE_TEXTURE.load(std::sync::atomic::Ordering::Relaxed);
        zfr_gl_trace_record_texture(bound, width, height);
        log!(
            "ZFR GL trace: glTexImage2D(tex {} level {}, internal {:#x}, {}x{}, fmt {:#x}, type {:#x}, data {})",
            bound,
            level,
            internalformat,
            width,
            height,
            format,
            type_,
            if null_data { "NULL" } else { "pixels" }
        );
    }
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pixels = if pixels.is_null() {
            std::ptr::null()
        } else {
            let pixel_count: GuestUSize = width.checked_mul(height).unwrap().try_into().unwrap();
            let size = image_size_estimate(pixel_count, format, type_);
            mem.ptr_at(pixels.cast::<u8>(), size).cast::<GLvoid>()
        };
        gles.TexImage2D(
            target,
            level,
            internalformat,
            width,
            height,
            border,
            format,
            type_,
            pixels,
        )
    })
}
fn glTexSubImage2D(
    env: &mut Environment,
    target: GLenum,
    level: GLint,
    xoffset: GLint,
    yoffset: GLint,
    width: GLsizei,
    height: GLsizei,
    format: GLenum,
    type_: GLenum,
    pixels: ConstVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let pixel_count: GuestUSize = width.checked_mul(height).unwrap().try_into().unwrap();
        let size = image_size_estimate(pixel_count, format, type_);
        let pixels = mem.ptr_at(pixels.cast::<u8>(), size).cast::<GLvoid>();
        gles.TexSubImage2D(
            target, level, xoffset, yoffset, width, height, format, type_, pixels,
        )
    })
}
fn glCompressedTexImage2D(
    env: &mut Environment,
    target: GLenum,
    level: GLint,
    internalformat: GLenum,
    width: GLsizei,
    height: GLsizei,
    border: GLint,
    image_size: GLsizei,
    data: ConstVoidPtr,
) {
    with_ctx_and_mem(env, |gles, mem| unsafe {
        let data = mem
            .ptr_at(data.cast::<u8>(), image_size.try_into().unwrap())
            .cast();
        gles.CompressedTexImage2D(
            target,
            level,
            internalformat,
            width,
            height,
            border,
            image_size,
            data,
        )
    })
}
fn glCopyTexImage2D(
    env: &mut Environment,
    target: GLenum,
    level: GLint,
    internalformat: GLenum,
    x: GLint,
    y: GLint,
    width: GLsizei,
    height: GLsizei,
    border: GLint,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.CopyTexImage2D(target, level, internalformat, x, y, width, height, border)
    })
}
fn glCopyTexSubImage2D(
    env: &mut Environment,
    target: GLenum,
    level: GLint,
    xoffset: GLint,
    yoffset: GLint,
    x: GLint,
    y: GLint,
    width: GLsizei,
    height: GLsizei,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.CopyTexSubImage2D(target, level, xoffset, yoffset, x, y, width, height)
    })
}
fn glTexEnvf(env: &mut Environment, target: GLenum, pname: GLenum, param: GLfloat) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexEnvf(target, pname, param)
    })
}
fn glTexEnvx(env: &mut Environment, target: GLenum, pname: GLenum, param: GLfixed) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexEnvx(target, pname, param)
    })
}
fn glTexEnvi(env: &mut Environment, target: GLenum, pname: GLenum, param: GLint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.TexEnvi(target, pname, param)
    })
}
fn glTexEnvfv(env: &mut Environment, target: GLenum, pname: GLenum, params: ConstPtr<GLfloat>) {
    assert!(
        target == gles11::TEXTURE_ENV || target == gles11::TEXTURE_FILTER_CONTROL_EXT,
        "target {target:#x}, pname {pname:#x}"
    );
    // TODO: GL_POINT_SPRITE_OES
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.TexEnvfv(target, pname, params) }
    })
}
fn glTexEnvxv(env: &mut Environment, target: GLenum, pname: GLenum, params: ConstPtr<GLfixed>) {
    // TODO: GL_POINT_SPRITE_OES
    assert!(target == gles11::TEXTURE_ENV);
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.TexEnvxv(target, pname, params) }
    })
}
fn glTexEnviv(env: &mut Environment, target: GLenum, pname: GLenum, params: ConstPtr<GLint>) {
    // TODO: GL_POINT_SPRITE_OES
    assert!(target == gles11::TEXTURE_ENV);
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at(params, 4 /* upper bound */);
        unsafe { gles.TexEnviv(target, pname, params) }
    })
}

fn glMultiTexCoord4f(
    env: &mut Environment,
    target: GLenum,
    s: GLfloat,
    t: GLfloat,
    r: GLfloat,
    q: GLfloat,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.MultiTexCoord4f(target, s, t, r, q)
    })
}
fn glMultiTexCoord4x(
    env: &mut Environment,
    target: GLenum,
    s: GLfixed,
    t: GLfixed,
    r: GLfixed,
    q: GLfixed,
) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.MultiTexCoord4x(target, s, t, r, q)
    })
}

// OES_framebuffer_object
fn glGenFramebuffersOES(env: &mut Environment, n: GLsizei, framebuffers: MutPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let framebuffers = mem.ptr_at_mut(framebuffers, n_usize);
        unsafe { gles.GenFramebuffersOES(n, framebuffers) }
    })
}
fn glGenRenderbuffersOES(env: &mut Environment, n: GLsizei, renderbuffers: MutPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let renderbuffers = mem.ptr_at_mut(renderbuffers, n_usize);
        unsafe { gles.GenRenderbuffersOES(n, renderbuffers) }
    })
}
fn glIsFramebufferOES(env: &mut Environment, framebuffer: GLuint) -> GLboolean {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.IsFramebufferOES(framebuffer)
    })
}
fn glIsRenderbufferOES(env: &mut Environment, renderbuffer: GLuint) -> GLboolean {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.IsRenderbufferOES(renderbuffer)
    })
}
fn glBindFramebufferOES(env: &mut Environment, target: GLenum, framebuffer: GLuint) {
    ZFR_GL_CURRENT_FBO.store(framebuffer, std::sync::atomic::Ordering::Relaxed);
    if zfr_gl_trace_enabled() {
        log!("ZFR GL trace: glBindFramebufferOES(target {:#x}, fbo {})", target, framebuffer);
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.BindFramebufferOES(target, framebuffer);

        // What is this framebuffer actually backed by? The scale hack can only
        // follow a renderbuffer it created itself (the drawable); a framebuffer
        // the app backed with its own texture has a size we cannot change.
        // Log once per framebuffer so the output stays readable.
        static SEEN: std::sync::OnceLock<std::sync::Mutex<std::collections::HashSet<GLuint>>> =
            std::sync::OnceLock::new();
        let seen = SEEN.get_or_init(|| std::sync::Mutex::new(std::collections::HashSet::new()));
        let fresh = seen.lock().map(|mut s| s.insert(framebuffer)).unwrap_or(false);
        if fresh && zfr_gl_trace_enabled() {
            let mut obj_type: GLint = 0;
            let mut obj_name: GLint = 0;
            gles.GetFramebufferAttachmentParameterivOES(
                target,
                gles11::COLOR_ATTACHMENT0_OES,
                0x8cd0, // GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE_OES
                &mut obj_type,
            );
            gles.GetFramebufferAttachmentParameterivOES(
                target,
                gles11::COLOR_ATTACHMENT0_OES,
                0x8cd1, // GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME_OES
                &mut obj_name,
            );
            // 0x8D41 == GL_RENDERBUFFER_OES, 0x1702 == GL_TEXTURE
            let detail;
            if obj_type == 0x8d41 {
                let mut w: GLint = 0;
                let mut h: GLint = 0;
                let mut prev: GLint = 0;
                gles.GetIntegerv(gles11::RENDERBUFFER_BINDING_OES, &mut prev);
                gles.BindRenderbufferOES(0x8d41, obj_name as GLuint);
                gles.GetRenderbufferParameterivOES(0x8d41, 0x8d42, &mut w); // WIDTH
                gles.GetRenderbufferParameterivOES(0x8d41, 0x8d43, &mut h); // HEIGHT
                gles.BindRenderbufferOES(0x8d41, prev as GLuint);
                detail = format!("renderbuffer {} ({}x{})", obj_name, w, h);
            } else if obj_type == 0x1702 {
                let (w, h) = zfr_gl_trace_texture_size(obj_name as GLuint).unwrap_or((-1, -1));
                detail = format!("texture {} ({}x{})", obj_name, w, h);
            } else {
                detail = format!("object type {:#x} name {}", obj_type, obj_name);
            }
            log!(
                "ZFR GL trace: fbo {} color attachment = {}",
                framebuffer,
                detail
            );
        }
    });

    // The viewport is sticky context state, but whether it should be scaled
    // depends on the render target that is now bound. ZFR sets the viewport
    // while the drawable is bound and then draws into its own texture-backed
    // framebuffer without setting it again, so re-derive it here or that pass
    // would inherit a viewport larger than its target.
    apply_guest_viewport(env, "re-applied after framebuffer bind");
}
fn glBindRenderbufferOES(env: &mut Environment, target: GLenum, renderbuffer: GLuint) {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.BindRenderbufferOES(target, renderbuffer)
    })
}
fn glRenderbufferStorageOES(
    env: &mut Environment,
    target: GLenum,
    internalformat: GLenum,
    width: GLsizei,
    height: GLsizei,
) {
    // Deliberately NOT scaled. This entry point only ever creates a
    // renderbuffer the app asked for; nothing else in the app's world knows it
    // is bigger, and the guest can query its true size. The drawable's
    // renderbuffer - the one render target that genuinely needs the scaled
    // size - is created by EAGLContext -renderbufferStorage:fromDrawable: in
    // eagl.rs, which does its own scaling and never comes through here.
    if zfr_gl_trace_enabled() {
        log!(
            "ZFR GL trace: glRenderbufferStorageOES(target {:#x}, {}x{}) - guest-owned, not scaled",
            target,
            width,
            height
        );
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.RenderbufferStorageOES(target, internalformat, width, height)
    })
}
fn glFramebufferRenderbufferOES(
    env: &mut Environment,
    target: GLenum,
    attachment: GLenum,
    renderbuffertarget: GLenum,
    renderbuffer: GLuint,
) {
    let context = zfr_gl_context_key(env);
    zfr_gl_invalidate_framebuffer_cache(context, zfr_gl_current_framebuffer());
    if zfr_gl_trace_enabled() {
        log!(
            "ZFR GL trace: glFramebufferRenderbufferOES(fbo {}, rbo {} drawable_backed {})",
            zfr_gl_current_framebuffer(),
            renderbuffer,
            zfr_gl_renderbuffer_is_drawable_backed(context, renderbuffer)
        );
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.FramebufferRenderbufferOES(target, attachment, renderbuffertarget, renderbuffer)
    })
}
fn glFramebufferTexture2DOES(
    env: &mut Environment,
    target: GLenum,
    attachment: GLenum,
    textarget: GLenum,
    texture: GLuint,
    level: i32,
) {
    zfr_gl_invalidate_framebuffer_cache(zfr_gl_context_key(env), zfr_gl_current_framebuffer());
    if zfr_gl_trace_enabled() {
        let size = zfr_gl_trace_texture_size(texture);
        log!(
            "ZFR GL trace: glFramebufferTexture2DOES(fbo {}, attachment {:#x}, tex {} size {:?}, level {})",
            zfr_gl_current_framebuffer(),
            attachment,
            texture,
            size,
            level
        );
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.FramebufferTexture2DOES(target, attachment, textarget, texture, level)
    })
}
fn glGetFramebufferAttachmentParameterivOES(
    env: &mut Environment,
    target: GLenum,
    attachment: GLenum,
    pname: GLenum,
    params: MutPtr<GLint>,
) {
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 1);
        unsafe { gles.GetFramebufferAttachmentParameterivOES(target, attachment, pname, params) }
    })
}
fn glGetRenderbufferParameterivOES(
    env: &mut Environment,
    target: GLenum,
    pname: GLenum,
    params: MutPtr<GLint>,
) {
    let (num, den) = (
        env.options.scale_hack.get(),
        env.options.scale_hack_den.get(),
    );
    with_ctx_and_mem(env, |gles, mem| {
        let params = mem.ptr_at_mut(params, 1);
        unsafe { gles.GetRenderbufferParameterivOES(target, pname, params) };
        // apply scale hack: scale down the reported size of the framebuffer,
        // assuming the framebuffer's true size is larger than it should be
        if pname == gles11::RENDERBUFFER_WIDTH_OES || pname == gles11::RENDERBUFFER_HEIGHT_OES {
            let reported = unsafe { params.read_unaligned() } as u32;
            unsafe {
                params.write_unaligned(crate::options::unscale_dim(reported, num, den) as GLint)
            }
        }
    })
}
fn glCheckFramebufferStatusOES(env: &mut Environment, target: GLenum) -> GLenum {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.CheckFramebufferStatusOES(target)
    })
}
fn glDeleteFramebuffersOES(env: &mut Environment, n: GLsizei, framebuffers: ConstPtr<GLuint>) {
    // The cached "is this render target scaled?" answers are keyed by
    // framebuffer name and refreshed whenever an attachment changes. A deleted
    // name may be reused later, but glFramebufferRenderbufferOES /
    // glFramebufferTexture2DOES invalidate the entry then, so there is nothing
    // to do here.
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let framebuffers = mem.ptr_at(framebuffers, n_usize);
        unsafe { gles.DeleteFramebuffersOES(n, framebuffers) }
    })
}
fn glDeleteRenderbuffersOES(env: &mut Environment, n: GLsizei, renderbuffers: ConstPtr<GLuint>) {
    with_ctx_and_mem(env, |gles, mem| {
        let n_usize: GuestUSize = n.try_into().unwrap();
        let renderbuffers = mem.ptr_at(renderbuffers, n_usize);
        unsafe { gles.DeleteRenderbuffersOES(n, renderbuffers) }
    })
}
fn glGenerateMipmapOES(env: &mut Environment, target: GLenum) {
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.GenerateMipmapOES(target) })
}

fn glGetBufferParameteriv(
    env: &mut Environment,
    target: GLenum,
    pname: GLenum,
    params: MutPtr<GLint>,
) {
    let params = env.mem.ptr_at_mut(params, 1);
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        gles.GetBufferParameteriv(target, pname, params)
    })
}
fn glMapBufferOES(env: &mut Environment, target: GLenum, access: GLenum) -> MutPtr<GLvoid> {
    //  "glMapBuffer maps to the client's address space the entire data store
    //  of the buffer object currently bound to target. The data can then be
    //  directly read and/or written relative to the returned pointer,
    //  depending on the specified access policy."
    // https://docs.gl/gl2/glMapBuffer
    //
    // We have to make an address space in the guest and "forward" those
    // reads/writes to the address space in the host, which is mapped to the
    // target buffer.
    // Since the mapped buffer can't be used until it's unmapped, we defer the
    // "forwarding" of read/writes until the moment the buffer is unmapped.
    assert!(matches!(target, ARRAY_BUFFER | ELEMENT_ARRAY_BUFFER));
    assert!(access == WRITE_ONLY_OES);
    let buffer_object_name = _get_currently_bound_buffer_object_name(env, target);
    let host_buffer = with_ctx_and_mem_no_skip(env, |gles, _mem| unsafe {
        gles.MapBufferOES(target, access)
    });
    if host_buffer.is_null() {
        nil.cast()
    } else {
        let buffer_size = _get_buffer_size(env, target) as u32;
        let guest_buffer: MutVoidPtr = env.mem.alloc(buffer_size).cast();
        // Copy host buffer to guest buffer
        unsafe {
            env.mem
                .bytes_at_mut(guest_buffer.cast(), buffer_size)
                .copy_from_slice(from_raw_parts(host_buffer as *mut u8, buffer_size as usize));
        }

        let current_ctx = env
            .framework_state
            .opengles
            .current_ctx_for_thread(env.current_thread);
        let current_ctx_host_object = env
            .objc
            .borrow_mut::<EAGLContextHostObject>(current_ctx.unwrap());
        assert!(current_ctx_host_object
            .mapped_buffers
            .insert(buffer_object_name, (guest_buffer, host_buffer))
            .is_none());

        guest_buffer
    }
}
fn glUnmapBufferOES(env: &mut Environment, target: GLenum) -> GLboolean {
    //  "A mapped data store must be unmapped with glUnmapBuffer before its
    //  buffer object is used. Otherwise an error will be generated by any GL
    //  command that attempts to dereference the buffer object's data store.
    //  When a data store is unmapped, the pointer to its data store becomes
    //  invalid."
    // https://docs.gl/gl2/glMapBuffer
    //
    // Since the mapped buffer can't be used until it's unmapped, we defer the
    // "forwarding" of read/writes until the moment the buffer is unmapped.
    // The guest buffer is deallocated here
    let buffer_object_name = _get_currently_bound_buffer_object_name(env, target);

    let current_ctx = env
        .framework_state
        .opengles
        .current_ctx_for_thread(env.current_thread);
    let current_ctx_host_object = env
        .objc
        .borrow_mut::<EAGLContextHostObject>(current_ctx.unwrap());

    if let Some((guest_buffer, host_buffer)) = current_ctx_host_object
        .mapped_buffers
        .remove(&buffer_object_name)
    {
        let buffer_size = _get_buffer_size(env, target) as u32;
        // Copy guest buffer to host buffer
        unsafe {
            host_buffer.copy_from(
                env.mem.bytes_at(guest_buffer.cast(), buffer_size).as_ptr() as *mut GLvoid,
                buffer_size as usize,
            );
        }
        env.mem.free(guest_buffer);
    }
    with_ctx_and_mem(env, |gles, _mem| unsafe { gles.UnmapBufferOES(target) })
}

/// If fog is enabled, check if the values for start and end distances
/// are equal. Apple platforms (even modern Mac OS) seem to handle that
/// gracefully, however, both Windows and Android have issues in those cases.
/// This workaround is required so Doom 2 RPG renders correctly.
/// It prevents divisions by zero in levels where fog is used and both
/// values are set to 10000.
unsafe fn clamp_fog_state_values(gles: &mut dyn GLES) -> Option<(f32, f32)> {
    let mut fogEnabled: GLboolean = 0;
    gles.GetBooleanv(gles11::FOG, &mut fogEnabled);
    if fogEnabled != 0 {
        let mut fogStart: GLfloat = 0.0;
        let mut fogEnd: GLfloat = 0.0;
        gles.GetFloatv(gles11::FOG_START, &mut fogStart);
        gles.GetFloatv(gles11::FOG_END, &mut fogEnd);
        if fogStart == fogEnd {
            let newFogStart = fogEnd - 0.001;
            gles.Fogf(gles11::FOG_START, newFogStart);
            return Some((fogStart, fogEnd));
        }
    }
    None
}
unsafe fn restore_fog_state_values(gles: &mut dyn GLES, from_backup: Option<(f32, f32)>) {
    if let Some((fogStart, fogEnd)) = from_backup {
        gles.Fogf(gles11::FOG_START, fogStart);
        gles.Fogf(gles11::FOG_END, fogEnd);
    }
}

pub const FUNCTIONS: FunctionExports = &[
    // Generic state manipulation
    export_c_func!(glGetError()),
    export_c_func!(glEnable(_)),
    export_c_func!(glIsEnabled(_)),
    export_c_func!(glDisable(_)),
    export_c_func!(glClientActiveTexture(_)),
    export_c_func!(glEnableClientState(_)),
    export_c_func!(glDisableClientState(_)),
    export_c_func!(glGetBooleanv(_, _)),
    export_c_func!(glGetFloatv(_, _)),
    export_c_func!(glGetIntegerv(_, _)),
    export_c_func!(glGetPointerv(_, _)),
    export_c_func!(glGetTexEnviv(_, _, _)),
    export_c_func!(glGetTexEnvfv(_, _, _)),
    export_c_func!(glHint(_, _)),
    export_c_func!(glFinish()),
    export_c_func!(glFlush()),
    export_c_func!(glGetString(_)),
    // Other state manipulation
    export_c_func!(glAlphaFunc(_, _)),
    export_c_func!(glAlphaFuncx(_, _)),
    export_c_func!(glBlendFunc(_, _)),
    export_c_func!(glBlendEquationOES(_)),
    export_c_func!(glColorMask(_, _, _, _)),
    export_c_func!(glClipPlanef(_, _)),
    export_c_func!(glClipPlanex(_, _)),
    export_c_func!(glCullFace(_)),
    export_c_func!(glDepthFunc(_)),
    export_c_func!(glDepthMask(_)),
    export_c_func!(glDepthRangef(_, _)),
    export_c_func!(glDepthRangex(_, _)),
    export_c_func!(glFrontFace(_)),
    export_c_func!(glPolygonOffset(_, _)),
    export_c_func!(glPolygonOffsetx(_, _)),
    export_c_func!(glSampleCoverage(_, _)),
    export_c_func!(glSampleCoveragex(_, _)),
    export_c_func!(glShadeModel(_)),
    export_c_func!(glScissor(_, _, _, _)),
    export_c_func!(glViewport(_, _, _, _)),
    export_c_func!(glLineWidth(_)),
    export_c_func!(glLineWidthx(_)),
    export_c_func!(glStencilFunc(_, _, _)),
    export_c_func!(glStencilOp(_, _, _)),
    export_c_func!(glStencilMask(_)),
    export_c_func!(glLogicOp(_)),
    // Points
    export_c_func!(glPointSize(_)),
    export_c_func!(glPointSizex(_)),
    export_c_func!(glPointParameterf(_, _)),
    export_c_func!(glPointParameterx(_, _)),
    export_c_func!(glPointParameterfv(_, _)),
    export_c_func!(glPointParameterxv(_, _)),
    // Lighting and materials
    export_c_func!(glFogf(_, _)),
    export_c_func!(glFogx(_, _)),
    export_c_func!(glFogfv(_, _)),
    export_c_func!(glFogxv(_, _)),
    export_c_func!(glLightf(_, _, _)),
    export_c_func!(glLightx(_, _, _)),
    export_c_func!(glLightfv(_, _, _)),
    export_c_func!(glLightxv(_, _, _)),
    export_c_func!(glLightModelf(_, _)),
    export_c_func!(glLightModelfv(_, _)),
    export_c_func!(glLightModelx(_, _)),
    export_c_func!(glLightModelxv(_, _)),
    export_c_func!(glMaterialf(_, _, _)),
    export_c_func!(glMaterialx(_, _, _)),
    export_c_func!(glMaterialfv(_, _, _)),
    export_c_func!(glMaterialxv(_, _, _)),
    // Buffers
    export_c_func!(glIsBuffer(_)),
    export_c_func!(glGenBuffers(_, _)),
    export_c_func!(glDeleteBuffers(_, _)),
    export_c_func!(glBindBuffer(_, _)),
    export_c_func!(glBufferData(_, _, _, _)),
    export_c_func!(glBufferSubData(_, _, _, _)),
    // Non-pointers
    export_c_func!(glColor4f(_, _, _, _)),
    export_c_func!(glColor4x(_, _, _, _)),
    export_c_func!(glColor4ub(_, _, _, _)),
    export_c_func!(glNormal3f(_, _, _)),
    export_c_func!(glNormal3x(_, _, _)),
    // Pointers
    export_c_func!(glColorPointer(_, _, _, _)),
    export_c_func!(glNormalPointer(_, _, _)),
    export_c_func!(glTexCoordPointer(_, _, _, _)),
    export_c_func!(glVertexPointer(_, _, _, _)),
    // Drawing
    export_c_func!(glDrawArrays(_, _, _)),
    export_c_func!(glDrawElements(_, _, _, _)),
    // Clearing
    export_c_func!(glClear(_)),
    export_c_func!(glClearColor(_, _, _, _)),
    export_c_func!(glClearColorx(_, _, _, _)),
    export_c_func!(glClearDepthf(_)),
    export_c_func!(glClearDepthx(_)),
    export_c_func!(glClearStencil(_)),
    // Matrix stack operations
    export_c_func!(glMatrixMode(_)),
    export_c_func!(glLoadIdentity()),
    export_c_func!(glLoadMatrixf(_)),
    export_c_func!(glLoadMatrixx(_)),
    export_c_func!(glMultMatrixf(_)),
    export_c_func!(glMultMatrixx(_)),
    export_c_func!(glPushMatrix()),
    export_c_func!(glPopMatrix()),
    export_c_func!(glOrthof(_, _, _, _, _, _)),
    export_c_func!(glOrthox(_, _, _, _, _, _)),
    export_c_func!(glFrustumf(_, _, _, _, _, _)),
    export_c_func!(glFrustumx(_, _, _, _, _, _)),
    export_c_func!(glRotatef(_, _, _, _)),
    export_c_func!(glRotatex(_, _, _, _)),
    export_c_func!(glScalef(_, _, _)),
    export_c_func!(glScalex(_, _, _)),
    export_c_func!(glTranslatef(_, _, _)),
    export_c_func!(glTranslatex(_, _, _)),
    // Textures
    export_c_func!(glPixelStorei(_, _)),
    export_c_func!(glReadPixels(_, _, _, _, _, _, _)),
    export_c_func!(glGenTextures(_, _)),
    export_c_func!(glDeleteTextures(_, _)),
    export_c_func!(glActiveTexture(_)),
    export_c_func!(glIsTexture(_)),
    export_c_func!(glBindTexture(_, _)),
    export_c_func!(glTexParameteri(_, _, _)),
    export_c_func!(glTexParameterf(_, _, _)),
    export_c_func!(glTexParameterx(_, _, _)),
    export_c_func!(glTexParameteriv(_, _, _)),
    export_c_func!(glTexParameterfv(_, _, _)),
    export_c_func!(glTexParameterxv(_, _, _)),
    export_c_func!(glTexImage2D(_, _, _, _, _, _, _, _, _)),
    export_c_func!(glTexSubImage2D(_, _, _, _, _, _, _, _, _)),
    export_c_func!(glCompressedTexImage2D(_, _, _, _, _, _, _, _)),
    export_c_func!(glCopyTexImage2D(_, _, _, _, _, _, _, _)),
    export_c_func!(glCopyTexSubImage2D(_, _, _, _, _, _, _, _)),
    export_c_func!(glTexEnvf(_, _, _)),
    export_c_func!(glTexEnvx(_, _, _)),
    export_c_func!(glTexEnvi(_, _, _)),
    export_c_func!(glTexEnvfv(_, _, _)),
    export_c_func!(glTexEnvxv(_, _, _)),
    export_c_func!(glTexEnviv(_, _, _)),
    export_c_func!(glMultiTexCoord4f(_, _, _, _, _)),
    export_c_func!(glMultiTexCoord4x(_, _, _, _, _)),
    // OES_framebuffer_object
    export_c_func!(glGenFramebuffersOES(_, _)),
    export_c_func!(glGenRenderbuffersOES(_, _)),
    export_c_func!(glIsFramebufferOES(_)),
    export_c_func!(glIsRenderbufferOES(_)),
    export_c_func!(glBindFramebufferOES(_, _)),
    export_c_func!(glBindRenderbufferOES(_, _)),
    export_c_func!(glRenderbufferStorageOES(_, _, _, _)),
    export_c_func!(glFramebufferRenderbufferOES(_, _, _, _)),
    export_c_func!(glFramebufferTexture2DOES(_, _, _, _, _)),
    export_c_func!(glGetFramebufferAttachmentParameterivOES(_, _, _, _)),
    export_c_func!(glGetRenderbufferParameterivOES(_, _, _)),
    export_c_func!(glCheckFramebufferStatusOES(_)),
    export_c_func!(glDeleteFramebuffersOES(_, _)),
    export_c_func!(glDeleteRenderbuffersOES(_, _)),
    export_c_func!(glGenerateMipmapOES(_)),
    export_c_func!(glGetBufferParameteriv(_, _, _)),
    export_c_func!(glMapBufferOES(_, _)),
    export_c_func!(glUnmapBufferOES(_)),
];

fn _get_currently_bound_buffer_object_name(env: &mut Environment, target: GLenum) -> GLuint {
    with_ctx_and_mem(env, |gles, _mem| unsafe {
        let pname = match target {
            ARRAY_BUFFER => VERTEX_ARRAY_BUFFER_BINDING,
            ELEMENT_ARRAY_BUFFER => ELEMENT_ARRAY_BUFFER_BINDING,
            _ => panic!(),
        };
        let currently_bound_buffer_name: GLuint = 0;
        gles.GetIntegerv(pname, &mut (currently_bound_buffer_name as GLint));
        currently_bound_buffer_name
    })
}

fn _get_buffer_size(env: &mut Environment, target: GLenum) -> GLint {
    with_ctx_and_mem(env, |gles, _mem| {
        let mut buffer_size: GLint = 0;
        unsafe { gles.GetBufferParameteriv(target, gles11::BUFFER_SIZE, &mut buffer_size) }
        buffer_size
    })
}
