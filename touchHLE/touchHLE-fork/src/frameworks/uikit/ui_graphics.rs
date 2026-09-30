/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIGraphics.h`

use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_graphics::cg_bitmap_context::{
    CGBitmapContextCreate, CGBitmapContextCreateImage,
};
use crate::frameworks::core_graphics::cg_color_space::{
    CGColorSpaceCreateDeviceRGB, CGColorSpaceRelease,
};
use crate::frameworks::core_graphics::cg_context::{
    CGContextRef, CGContextRelease, CGContextRetain,
};
use crate::frameworks::core_graphics::cg_image::{kCGImageAlphaPremultipliedLast, CGImageRelease};
use crate::frameworks::core_graphics::CGSize;
use crate::objc::{msg_class, nil};
use crate::Environment;

#[derive(Default)]
pub(super) struct State {
    pub(super) context_stack: Vec<CGContextRef>,
}

pub fn UIGraphicsPushContext(env: &mut Environment, context: CGContextRef) {
    CGContextRetain(env, context);
    env.framework_state
        .uikit
        .ui_graphics
        .context_stack
        .push(context);
}
pub fn UIGraphicsPopContext(env: &mut Environment) {
    let context = env.framework_state.uikit.ui_graphics.context_stack.pop();
    CGContextRelease(env, context.unwrap());
}
pub fn UIGraphicsGetCurrentContext(env: &mut Environment) -> CGContextRef {
    env.framework_state
        .uikit
        .ui_graphics
        .context_stack
        .last()
        .copied()
        .unwrap_or(nil)
}

fn UIGraphicsBeginImageContext(env: &mut Environment, size: CGSize) {
    UIGraphicsBeginImageContextWithOptions(env, size, false, 1.0)
}

fn UIGraphicsBeginImageContextWithOptions(
    env: &mut Environment,
    size: CGSize,
    _opaque: bool,
    scale: f32,
) {
    let scale = if scale == 0.0 { 1.0 } else { scale };
    let width = (size.width * scale).ceil().max(1.0) as u32;
    let height = (size.height * scale).ceil().max(1.0) as u32;
    let color_space = CGColorSpaceCreateDeviceRGB(env);
    let context = CGBitmapContextCreate(
        env,
        nil.cast(),
        width,
        height,
        8,
        width * 4,
        color_space,
        kCGImageAlphaPremultipliedLast,
    );
    CGColorSpaceRelease(env, color_space);
    UIGraphicsPushContext(env, context);
    CGContextRelease(env, context);
}

fn UIGraphicsGetImageFromCurrentImageContext(env: &mut Environment) -> crate::objc::id {
    let context = UIGraphicsGetCurrentContext(env);
    if context == nil {
        return nil;
    }
    let cg_image = CGBitmapContextCreateImage(env, context);
    let image = msg_class![env; UIImage imageWithCGImage:cg_image];
    CGImageRelease(env, cg_image);
    image
}

fn UIGraphicsEndImageContext(env: &mut Environment) {
    if !env
        .framework_state
        .uikit
        .ui_graphics
        .context_stack
        .is_empty()
    {
        UIGraphicsPopContext(env);
    }
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(UIGraphicsPushContext(_)),
    export_c_func!(UIGraphicsPopContext()),
    export_c_func!(UIGraphicsGetCurrentContext()),
    export_c_func!(UIGraphicsBeginImageContext(_)),
    export_c_func!(UIGraphicsBeginImageContextWithOptions(_, _, _)),
    export_c_func!(UIGraphicsGetImageFromCurrentImageContext()),
    export_c_func!(UIGraphicsEndImageContext()),
];
