/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CGImage.h`

use super::cg_color_space::{
    kCGColorSpaceGenericRGB, kCGColorSpaceModelMonochrome, kCGColorSpaceModelRGB,
    CGColorSpaceCreateWithName, CGColorSpaceGetModel, CGColorSpaceRef,
};
use super::cg_data_provider::{self, CGDataProviderRef};
use super::{CGFloat, CGRect};
use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_foundation::{CFRelease, CFRetain, CFTypeRef};
use crate::frameworks::foundation::ns_string;
use crate::image::Image;
use crate::mem::{ConstPtr, GuestUSize};
use crate::objc::{autorelease, nil, objc_classes, ClassExports, HostObject, ObjC};
use crate::Environment;

pub type CGImageAlphaInfo = u32;
pub const kCGImageAlphaNone: CGImageAlphaInfo = 0;
pub const kCGImageAlphaPremultipliedLast: CGImageAlphaInfo = 1;
pub const kCGImageAlphaPremultipliedFirst: CGImageAlphaInfo = 2;
pub const kCGImageAlphaLast: CGImageAlphaInfo = 3;
pub const kCGImageAlphaFirst: CGImageAlphaInfo = 4;
pub const kCGImageAlphaNoneSkipLast: CGImageAlphaInfo = 5;
pub const kCGImageAlphaNoneSkipFirst: CGImageAlphaInfo = 6;
pub const kCGImageAlphaOnly: CGImageAlphaInfo = 7;

pub type CGImageByteOrderInfo = u32;
pub const kCGImageByteOrderMask: CGImageByteOrderInfo = 0x7000;
pub const kCGImageByteOrderDefault: CGImageByteOrderInfo = 0 << 12;
#[allow(dead_code)]
pub const kCGImageByteOrder16Little: CGImageByteOrderInfo = 1 << 12;
#[allow(dead_code)]
pub const kCGImageByteOrder32Little: CGImageByteOrderInfo = 2 << 12;
#[allow(dead_code)]
pub const kCGImageByteOrder16Big: CGImageByteOrderInfo = 3 << 12;
pub const kCGImageByteOrder32Big: CGImageByteOrderInfo = 4 << 12;

pub type CGBitmapInfo = u32;
pub const kCGBitmapAlphaInfoMask: CGBitmapInfo = 0x1F; // huh, it's not 0x7?
pub const kCGBitmapByteOrderMask: CGBitmapInfo = kCGImageByteOrderMask;
// TODO: other stuff in this enum (for now, always assert the rest is 0)

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

// CGImage seems to be a CFType-based type, but in our implementation those
// are just Objective-C types, so we need a class for it, but its name is not
// visible anywhere.
@implementation _touchHLE_CGImage: NSObject
@end

};

struct CGImageHostObject {
    image: Image,
}
impl HostObject for CGImageHostObject {}

pub type CGImageRef = CFTypeRef;
pub fn CGImageRelease(env: &mut Environment, c: CGImageRef) {
    if !c.is_null() {
        CFRelease(env, c);
    }
}
pub fn CGImageRetain(env: &mut Environment, c: CGImageRef) -> CGImageRef {
    if !c.is_null() {
        CFRetain(env, c)
    } else {
        c
    }
}

/// Shortcut for use by `UIImage`: directly construct a `CGImage` instance from
/// an [Image] instance.
pub fn from_image(env: &mut Environment, image: Image) -> CGImageRef {
    let host_obj = Box::new(CGImageHostObject { image });
    let class = env.objc.get_known_class("_touchHLE_CGImage", &mut env.mem);
    env.objc.alloc_object(class, host_obj, &mut env.mem)
}

/// Shortcut for use by `CGBitmapContext` etc: borrow the [Image] from a
/// `CGImage` instance.
pub fn borrow_image(objc: &ObjC, image: CGImageRef) -> &Image {
    &objc.borrow::<CGImageHostObject>(image).image
}

/// Shortcut used by the app picker, counterpart to [borrow_image].
/// FIXME: This should not exist!
pub fn borrow_image_mut(objc: &mut ObjC, image: CGImageRef) -> &mut Image {
    &mut objc.borrow_mut::<CGImageHostObject>(image).image
}

// TODO: More create methods.

fn CGImageCreateCopyWithColorSpace(
    env: &mut Environment,
    image: CGImageRef,
    color_space: CGColorSpaceRef,
) -> CGImageRef {
    let image_color_space = CGImageGetColorSpace(env, image);
    assert_eq!(
        CGColorSpaceGetModel(env, image_color_space),
        CGColorSpaceGetModel(env, color_space)
    );
    // If color space matches, we could just create a copy.
    let new_image = env.objc.borrow::<CGImageHostObject>(image).image.clone();
    from_image(env, new_image)
}

pub fn CGImageCreateWithImageInRect(
    env: &mut Environment,
    image: CGImageRef,
    rect: CGRect,
) -> CGImageRef {
    let CGRect { origin, size } = rect;
    if image == nil || size.width <= 0.0 || size.height <= 0.0 {
        return nil;
    }

    let (pixels, dimensions) = {
        let image = env.objc.borrow::<CGImageHostObject>(image);
        let (source_width, source_height) = image.image.dimensions();

        let x0 = origin.x.floor().max(0.0).min(source_width as f32) as u32;
        let y0 = origin.y.floor().max(0.0).min(source_height as f32) as u32;
        let x1 = (origin.x + size.width)
            .ceil()
            .max(0.0)
            .min(source_width as f32) as u32;
        let y1 = (origin.y + size.height)
            .ceil()
            .max(0.0)
            .min(source_height as f32) as u32;

        if x1 <= x0 || y1 <= y0 {
            return nil;
        }

        let crop_width = x1 - x0;
        let crop_height = y1 - y0;
        let mut pixels = Vec::with_capacity(crop_width as usize * crop_height as usize * 4);
        let source_pixels = image.image.pixels();
        let source_stride = source_width as usize * 4;
        let row_len = crop_width as usize * 4;

        for y in y0..y1 {
            let start = y as usize * source_stride + x0 as usize * 4;
            pixels.extend_from_slice(&source_pixels[start..start + row_len]);
        }

        (pixels, (crop_width, crop_height))
    };

    from_image(env, Image::from_pixel_vec(pixels, dimensions))
}

fn transparent_image(env: &mut Environment, width: GuestUSize, height: GuestUSize) -> CGImageRef {
    let width = width.max(1);
    let height = height.max(1);
    from_image(
        env,
        Image::from_pixel_vec(
            vec![0; width as usize * height as usize * 4],
            (width, height),
        ),
    )
}

fn CGImageCreate(
    env: &mut Environment,
    width: GuestUSize,
    height: GuestUSize,
    bits_per_component: GuestUSize,
    bits_per_pixel: GuestUSize,
    bytes_per_row: GuestUSize,
    color_space: CGColorSpaceRef,
    bitmap_info: CGBitmapInfo,
    provider: CGDataProviderRef,
    _decode: ConstPtr<CGFloat>,
    _should_interpolate: bool,
    _intent: i32,
) -> CGImageRef {
    if width == 0 || height == 0 {
        return nil;
    }

    if bits_per_component != 8 || bytes_per_row == 0 || provider == nil {
        return transparent_image(env, width, height);
    }

    let color_model = if color_space == nil {
        kCGColorSpaceModelRGB
    } else {
        CGColorSpaceGetModel(env, color_space)
    };
    let alpha_info = bitmap_info & kCGBitmapAlphaInfoMask;
    let byte_order = bitmap_info & kCGBitmapByteOrderMask;
    if byte_order != kCGImageByteOrderDefault && byte_order != kCGImageByteOrder32Big {
        return transparent_image(env, width, height);
    }

    let source = cg_data_provider::borrow_bytes(env, provider);
    let required_len = bytes_per_row as usize * height as usize;
    if source.len() < required_len {
        return transparent_image(env, width, height);
    }

    let mut pixels = Vec::with_capacity(width as usize * height as usize * 4);
    for y in 0..height as usize {
        let row = &source[y * bytes_per_row as usize..][..bytes_per_row as usize];
        for x in 0..width as usize {
            let (r, g, b, a) = match (color_model, bits_per_pixel, alpha_info) {
                (kCGColorSpaceModelRGB, 24, kCGImageAlphaNone) => {
                    let offset = x * 3;
                    if offset + 2 >= row.len() {
                        return transparent_image(env, width, height);
                    }
                    (row[offset], row[offset + 1], row[offset + 2], 255)
                }
                (
                    kCGColorSpaceModelRGB,
                    32,
                    kCGImageAlphaNone
                    | kCGImageAlphaPremultipliedLast
                    | kCGImageAlphaLast
                    | kCGImageAlphaNoneSkipLast,
                ) => {
                    let offset = x * 4;
                    if offset + 3 >= row.len() {
                        return transparent_image(env, width, height);
                    }
                    let alpha =
                        if matches!(alpha_info, kCGImageAlphaNone | kCGImageAlphaNoneSkipLast) {
                            255
                        } else {
                            row[offset + 3]
                        };
                    (row[offset], row[offset + 1], row[offset + 2], alpha)
                }
                (
                    kCGColorSpaceModelRGB,
                    32,
                    kCGImageAlphaPremultipliedFirst
                    | kCGImageAlphaFirst
                    | kCGImageAlphaNoneSkipFirst,
                ) => {
                    let offset = x * 4;
                    if offset + 3 >= row.len() {
                        return transparent_image(env, width, height);
                    }
                    let alpha = if alpha_info == kCGImageAlphaNoneSkipFirst {
                        255
                    } else {
                        row[offset]
                    };
                    (row[offset + 1], row[offset + 2], row[offset + 3], alpha)
                }
                (kCGColorSpaceModelMonochrome, 8, kCGImageAlphaNone | kCGImageAlphaOnly) => {
                    if x >= row.len() {
                        return transparent_image(env, width, height);
                    }
                    let value = row[x];
                    if alpha_info == kCGImageAlphaOnly {
                        (255, 255, 255, value)
                    } else {
                        (value, value, value, 255)
                    }
                }
                (
                    kCGColorSpaceModelMonochrome,
                    16,
                    kCGImageAlphaLast | kCGImageAlphaPremultipliedLast | kCGImageAlphaNoneSkipLast,
                ) => {
                    let offset = x * 2;
                    if offset + 1 >= row.len() {
                        return transparent_image(env, width, height);
                    }
                    let value = row[offset];
                    let alpha = if alpha_info == kCGImageAlphaNoneSkipLast {
                        255
                    } else {
                        row[offset + 1]
                    };
                    (value, value, value, alpha)
                }
                _ => {
                    log!(
                        "CGImageCreate unsupported format: {}x{}, bpc {}, bpp {}, bpr {}, color model {}, bitmap info {:#x}",
                        width,
                        height,
                        bits_per_component,
                        bits_per_pixel,
                        bytes_per_row,
                        color_model,
                        bitmap_info
                    );
                    return transparent_image(env, width, height);
                }
            };
            pixels.extend_from_slice(&[r, g, b, a]);
        }
    }

    from_image(env, Image::from_pixel_vec(pixels, (width, height)))
}

fn CGImageCreateWithPNGDataProvider(
    env: &mut Environment,
    source: CGDataProviderRef,
    decode: ConstPtr<CGFloat>,
    _should_interpolate: bool, // TODO
    _intent: i32,              // TODO (should be CGColorRenderingIntent)
) -> CGImageRef {
    assert!(decode.is_null()); // TODO

    let bytes = cg_data_provider::borrow_bytes(env, source);
    let Ok(image) = Image::from_bytes(bytes) else {
        // Docs don't say what happens on failure, but this would make sense.
        return nil;
    };

    from_image(env, image)
}

fn CGImageCreateWithJPEGDataProvider(
    env: &mut Environment,
    source: CGDataProviderRef,
    decode: ConstPtr<CGFloat>,
    _should_interpolate: bool, // TODO
    _intent: i32,              // TODO (should be CGColorRenderingIntent)
) -> CGImageRef {
    assert!(decode.is_null());

    let bytes = cg_data_provider::borrow_bytes(env, source);
    let Ok(image) = Image::from_bytes(bytes) else {
        // Docs don't say what happens on failure, but this would make sense.
        return nil;
    };

    from_image(env, image)
}

fn CGImageGetAlphaInfo(_env: &mut Environment, _image: CGImageRef) -> CGImageAlphaInfo {
    // our Image type always returns premultiplied RGBA
    // (the premultiplied part must match what the real UIImage does, but
    // considering CgBI's design, maybe the order doesn't?)
    kCGImageAlphaPremultipliedLast
}

fn CGImageGetColorSpace(env: &mut Environment, _image: CGImageRef) -> CGColorSpaceRef {
    // Caller must release
    // FIXME: what if a loaded image is not sRGB?

    let srgb_name = ns_string::get_static_str(env, kCGColorSpaceGenericRGB);
    CGColorSpaceCreateWithName(env, srgb_name)
}

pub fn CGImageGetWidth(env: &mut Environment, image: CGImageRef) -> GuestUSize {
    let (width, _height) = env
        .objc
        .borrow::<CGImageHostObject>(image)
        .image
        .dimensions();
    width
}
pub fn CGImageGetHeight(env: &mut Environment, image: CGImageRef) -> GuestUSize {
    let (_width, height) = env
        .objc
        .borrow::<CGImageHostObject>(image)
        .image
        .dimensions();
    height
}
fn CGImageGetBitsPerPixel(_env: &mut Environment, _image: CGImageRef) -> GuestUSize {
    32
}
fn CGImageGetBytesPerRow(env: &mut Environment, image: CGImageRef) -> GuestUSize {
    let (width, _height) = env
        .objc
        .borrow::<CGImageHostObject>(image)
        .image
        .dimensions();
    width * 4
}

fn CGImageGetDataProvider(env: &mut Environment, image: CGImageRef) -> CGDataProviderRef {
    // CGImageGetDataProvider() seems to be intended to return the underlying
    // data provider that is retained by the CGImage. That's not how CGImage is
    // implemented here though, so instead we make a data provider that
    // retains the CGImage: exactly the opposite approach!
    let cg_data_provider = cg_data_provider::from_cg_image(env, image);
    // CGImageGetDataProvider() isn't meant to return a new object, so the
    // caller won't free this. The CGImage can't retain the CGDataProvider
    // without causing a cycle, so let's autorelease it instead.
    autorelease(env, cg_data_provider)
}

fn CGImageGetBitsPerComponent(_: &mut Environment, _: CGImageRef) -> GuestUSize {
    8 // Fix this when we support anything else
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CGImageRelease(_)),
    export_c_func!(CGImageRetain(_)),
    export_c_func!(CGImageCreate(_, _, _, _, _, _, _, _, _, _, _)),
    export_c_func!(CGImageCreateCopyWithColorSpace(_, _)),
    export_c_func!(CGImageCreateWithImageInRect(_, _)),
    export_c_func!(CGImageCreateWithPNGDataProvider(_, _, _, _)),
    export_c_func!(CGImageCreateWithJPEGDataProvider(_, _, _, _)),
    export_c_func!(CGImageGetAlphaInfo(_)),
    export_c_func!(CGImageGetColorSpace(_)),
    export_c_func!(CGImageGetWidth(_)),
    export_c_func!(CGImageGetHeight(_)),
    export_c_func!(CGImageGetBitsPerPixel(_)),
    export_c_func!(CGImageGetBytesPerRow(_)),
    export_c_func!(CGImageGetDataProvider(_)),
    export_c_func!(CGImageGetBitsPerComponent(_)),
];
