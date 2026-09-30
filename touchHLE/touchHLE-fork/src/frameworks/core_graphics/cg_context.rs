/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CGContext.h`

use super::cg_affine_transform::CGAffineTransform;
use super::cg_image::{CGImageRef, CGImageRelease, CGImageRetain};
use super::{cg_bitmap_context, cg_color, CGFloat, CGRect};
use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_foundation::{CFRelease, CFRetain, CFTypeRef};
use crate::frameworks::core_graphics::cg_bitmap_context::{
    CGBitmapContextGetHeight, CGBitmapContextGetWidth,
};
use crate::frameworks::core_graphics::cg_color::CGColorRef;
use crate::frameworks::core_graphics::cg_geometry::CGPointZero;
use crate::objc::{objc_classes, ClassExports, HostObject};
use crate::Environment;

type CGInterpolationQuality = i32;
pub(super) type CGBlendMode = i32;
pub(super) const K_CG_BLEND_MODE_NORMAL: CGBlendMode = 0;
pub(super) const K_CG_BLEND_MODE_CLEAR: CGBlendMode = 16;
pub(super) const K_CG_BLEND_MODE_COPY: CGBlendMode = 17;

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

// CGContext seems to be a CFType-based type, but in our implementation those
// are just Objective-C types, so we need a class for it, but its name is not
// visible anywhere.
@implementation _touchHLE_CGContext: NSObject

- (())dealloc {
    let (bitmap_data, masks_to_release) = {
        let host_obj = env.objc.borrow::<CGContextHostObject>(this);
        let CGContextSubclass::CGBitmapContext(bitmap_data) = host_obj.subclass;
        let mut masks_to_release: Vec<_> = host_obj
            .state_stack
            .iter()
            .filter_map(|state| state.clip_mask.map(|(_, mask)| mask))
            .collect();
        if let Some((_, mask)) = host_obj.clip_mask {
            masks_to_release.push(mask);
        }
        (bitmap_data, masks_to_release)
    };
    if bitmap_data.data_is_owned {
        env.mem.free(bitmap_data.data);
    }
    for mask in masks_to_release {
        CGImageRelease(env, mask);
    }

    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};

pub(super) struct CGContextHostObject {
    pub(super) subclass: CGContextSubclass,
    pub(super) rgb_fill_color: (CGFloat, CGFloat, CGFloat, CGFloat),
    pub(super) blend_mode: CGBlendMode,
    /// Current transform.
    pub(super) transform: CGAffineTransform,
    pub(super) clip_mask: Option<(CGRect, CGImageRef)>,
    // TODO: keep more states saved once they are implemented
    pub(super) state_stack: Vec<CGContextState>,
}
impl HostObject for CGContextHostObject {}

pub(super) enum CGContextSubclass {
    CGBitmapContext(cg_bitmap_context::CGBitmapContextData),
}

pub(super) struct CGContextState {
    rgb_fill_color: (CGFloat, CGFloat, CGFloat, CGFloat),
    blend_mode: CGBlendMode,
    transform: CGAffineTransform,
    clip_mask: Option<(CGRect, CGImageRef)>,
}

pub type CGContextRef = CFTypeRef;

pub fn CGContextRelease(env: &mut Environment, c: CGContextRef) {
    if !c.is_null() {
        CFRelease(env, c);
    }
}
pub fn CGContextRetain(env: &mut Environment, c: CGContextRef) -> CGContextRef {
    if !c.is_null() {
        CFRetain(env, c)
    } else {
        c
    }
}

fn CGContextSetFillColorWithColor(env: &mut Environment, context: CGContextRef, color: CGColorRef) {
    let (r, g, b, a) = cg_color::to_rgba(&env.objc, color);
    CGContextSetRGBFillColor(env, context, r, g, b, a)
}

pub fn CGContextSetRGBFillColor(
    env: &mut Environment,
    context: CGContextRef,
    red: CGFloat,
    green: CGFloat,
    blue: CGFloat,
    alpha: CGFloat,
) {
    let color = (red, green, blue, alpha);
    env.objc
        .borrow_mut::<CGContextHostObject>(context)
        .rgb_fill_color = color;
}

fn CGContextSetGrayFillColor(
    env: &mut Environment,
    context: CGContextRef,
    gray: CGFloat,
    alpha: CGFloat,
) {
    let color = (gray, gray, gray, alpha);
    env.objc
        .borrow_mut::<CGContextHostObject>(context)
        .rgb_fill_color = color;
}

fn CGContextSetBlendMode(env: &mut Environment, context: CGContextRef, mode: CGBlendMode) {
    // Keep unsupported blend modes non-fatal. The bitmap drawer currently
    // handles Normal, Clear and Copy explicitly; other modes fall back to
    // normal alpha blending.
    env.objc
        .borrow_mut::<CGContextHostObject>(context)
        .blend_mode = mode;
}

pub fn CGContextFillRect(env: &mut Environment, context: CGContextRef, rect: CGRect) {
    cg_bitmap_context::fill_rect(env, context, rect, /* clear: */ false);
}

pub fn CGContextClearRect(env: &mut Environment, context: CGContextRef, rect: CGRect) {
    cg_bitmap_context::fill_rect(env, context, rect, /* clear: */ true);
}

fn CGContextClipToRect(env: &mut Environment, context: CGContextRef, rect: CGRect) {
    if rect.origin == CGPointZero
        && rect.size.height == CGBitmapContextGetHeight(env, context) as f32
        && rect.size.width == CGBitmapContextGetWidth(env, context) as f32
    {
        assert!(env
            .objc
            .borrow_mut::<CGContextHostObject>(context)
            .transform
            .is_identity());
        // All good, clipping is not needed!
        return;
    }
    todo!();
}

fn CGContextClipToMask(
    env: &mut Environment,
    context: CGContextRef,
    rect: CGRect,
    mask: CGImageRef,
) {
    if mask.is_null() || rect.size.width <= 0.0 || rect.size.height <= 0.0 {
        return;
    }
    CGImageRetain(env, mask);
    let old_mask = {
        let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
        std::mem::replace(&mut host_obj.clip_mask, Some((rect, mask)))
    };
    if let Some((_, old_mask)) = old_mask {
        CGImageRelease(env, old_mask);
    }
}

pub fn CGContextConcatCTM(
    env: &mut Environment,
    context: CGContextRef,
    transform: CGAffineTransform,
) {
    log_dbg!("CGContextConcatCTM({:?})", transform);
    let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
    host_obj.transform = transform.concat(host_obj.transform);
}
pub fn CGContextGetCTM(env: &mut Environment, context: CGContextRef) -> CGAffineTransform {
    let res = env.objc.borrow::<CGContextHostObject>(context).transform;
    log_dbg!("CGContextGetCTM() => {:?}", res);
    res
}
pub fn CGContextRotateCTM(env: &mut Environment, context: CGContextRef, angle: CGFloat) {
    log_dbg!("CGContextRotateCTM({:?})", angle);
    let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
    host_obj.transform = host_obj.transform.rotate(angle);
}
pub fn CGContextScaleCTM(env: &mut Environment, context: CGContextRef, x: CGFloat, y: CGFloat) {
    log_dbg!("CGContextScaleCTM({:?})", (x, y));
    let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
    host_obj.transform = host_obj.transform.scale(x, y);
}
pub fn CGContextTranslateCTM(
    env: &mut Environment,
    context: CGContextRef,
    tx: CGFloat,
    ty: CGFloat,
) {
    log_dbg!("CGContextTranslateCTM({:?})", (tx, ty));
    let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
    host_obj.transform = host_obj.transform.translate(tx, ty);
}

pub fn CGContextDrawImage(
    env: &mut Environment,
    context: CGContextRef,
    rect: CGRect,
    image: CGImageRef,
) {
    cg_bitmap_context::draw_image(env, context, rect, image);
}

pub fn CGContextSaveGState(env: &mut Environment, context: CGContextRef) {
    let state = {
        let host_obj = env.objc.borrow::<CGContextHostObject>(context);
        CGContextState {
            rgb_fill_color: host_obj.rgb_fill_color,
            blend_mode: host_obj.blend_mode,
            transform: host_obj.transform,
            clip_mask: host_obj.clip_mask,
        }
    };
    if let Some((_, mask)) = state.clip_mask {
        CGImageRetain(env, mask);
    }
    env.objc
        .borrow_mut::<CGContextHostObject>(context)
        .state_stack
        .push(state);
}

pub fn CGContextRestoreGState(env: &mut Environment, context: CGContextRef) {
    let (state, old_mask) = {
        let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
        (host_obj.state_stack.pop().unwrap(), host_obj.clip_mask)
    };
    if let Some((_, mask)) = old_mask {
        CGImageRelease(env, mask);
    }
    let host_obj = env.objc.borrow_mut::<CGContextHostObject>(context);
    host_obj.rgb_fill_color = state.rgb_fill_color;
    host_obj.blend_mode = state.blend_mode;
    host_obj.transform = state.transform;
    host_obj.clip_mask = state.clip_mask;
}

fn CGContextSetInterpolationQuality(
    _env: &mut Environment,
    context: CGContextRef,
    quality: CGInterpolationQuality,
) {
    log!(
        "TODO: CGContextSetInterpolationQuality({:?}, {:?})",
        context,
        quality
    );
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CGContextRetain(_)),
    export_c_func!(CGContextRelease(_)),
    export_c_func!(CGContextSetFillColorWithColor(_, _)),
    export_c_func!(CGContextSetRGBFillColor(_, _, _, _, _)),
    export_c_func!(CGContextSetGrayFillColor(_, _, _)),
    export_c_func!(CGContextSetBlendMode(_, _)),
    export_c_func!(CGContextFillRect(_, _)),
    export_c_func!(CGContextClearRect(_, _)),
    export_c_func!(CGContextClipToRect(_, _)),
    export_c_func!(CGContextClipToMask(_, _, _)),
    export_c_func!(CGContextConcatCTM(_, _)),
    export_c_func!(CGContextGetCTM(_)),
    export_c_func!(CGContextRotateCTM(_, _)),
    export_c_func!(CGContextScaleCTM(_, _, _)),
    export_c_func!(CGContextTranslateCTM(_, _, _)),
    export_c_func!(CGContextDrawImage(_, _, _)),
    export_c_func!(CGContextSaveGState(_)),
    export_c_func!(CGContextRestoreGState(_)),
    export_c_func!(CGContextSetInterpolationQuality(_, _)),
];
