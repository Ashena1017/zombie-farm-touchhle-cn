/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIImage`.

use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_graphics::cg_context::{
    CGContextDrawImage, CGContextRestoreGState, CGContextSaveGState, CGContextScaleCTM,
    CGContextTranslateCTM,
};
use crate::frameworks::core_graphics::cg_image::{
    self, CGImageCreateWithImageInRect, CGImageGetHeight, CGImageGetWidth, CGImageRef,
    CGImageRelease, CGImageRetain,
};
use crate::frameworks::core_graphics::{CGFloat, CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_string::get_static_str;
use crate::frameworks::foundation::{ns_data, ns_string, NSInteger, NSUInteger};
use crate::frameworks::uikit::ui_graphics::UIGraphicsGetCurrentContext;
use crate::fs::GuestPath;
use crate::image::Image;
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject,
    NSZonePtr,
};
use crate::Environment;
use std::collections::HashMap;

const CACHE_SIZE: usize = 10;

#[derive(Default)]
pub struct State {
    /// Cache of images for `[UIImage imageNamed:]` method.
    /// Images are explicitly retained.
    cached_images: HashMap<String, id>,
}
impl State {
    fn get(env: &Environment) -> &Self {
        &env.framework_state.uikit.ui_image
    }
    fn get_mut(env: &mut Environment) -> &mut Self {
        &mut env.framework_state.uikit.ui_image
    }
}

fn data_from_static_bytes(env: &mut Environment, bytes: &[u8]) -> id {
    let length: NSUInteger = bytes.len().try_into().unwrap();
    let guest_bytes = env.mem.alloc(length);
    env.mem
        .bytes_at_mut(guest_bytes.cast(), length)
        .copy_from_slice(bytes);
    msg_class![env; NSData dataWithBytesNoCopy:guest_bytes length:length freeWhenDone:true]
}

fn UIImageJPEGRepresentation(env: &mut Environment, image: id, compression_quality: CGFloat) -> id {
    log_dbg!(
        "UIImageJPEGRepresentation({:?}, quality {})",
        image,
        compression_quality
    );
    if image == nil {
        return nil;
    }

    // Zombie Farm only needs non-empty attachment data for the email-sharing
    // path. A SOI+EOI marker pair is enough for MessageUI callers here because
    // the image is never decoded again inside touchHLE.
    data_from_static_bytes(env, &[0xff, 0xd8, 0xff, 0xd9])
}

fn UIImagePNGRepresentation(env: &mut Environment, image: id) -> id {
    log_dbg!("UIImagePNGRepresentation({:?})", image);
    if image == nil {
        return nil;
    }

    // 1x1 transparent PNG.
    const PNG_1X1_TRANSPARENT: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
        0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f,
        0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00,
        0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ];
    data_from_static_bytes(env, PNG_1X1_TRANSPARENT)
}

struct UIImageHostObject {
    cg_image: CGImageRef,
    stretch_caps: Option<(NSInteger, NSInteger)>,
}
impl HostObject for UIImageHostObject {}

fn zombie_farm_image_alias(name: &str) -> Option<&'static str> {
    match name {
        "textBox.png" => Some("slide_panel_input_cell.png"),
        "cellTextBg_82.png" => Some("slide_panel_name_cell.png"),
        "cellTextBg_small_42.png" => Some("slide_panel_btn_cell.png"),
        "icon_person.png" => Some("main_panel_name_cell_image_cover.png"),
        _ => None,
    }
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIImage: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(UIImageHostObject {
        cg_image: nil,
        stretch_caps: None,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)imageWithCGImage:(CGImageRef)cg_image {
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithCGImage:cg_image];
    autorelease(env, new)
}

+ (id)imageNamed:(id)name { // NSString*
    let bundle: id = msg_class![env; NSBundle mainBundle];
    let bundle_id = env.bundle.bundle_identifier().to_string();
    let name_str = ns_string::to_rust_string(env, name).to_string();
    let mut path: id = msg![env; bundle pathForResource:name ofType:nil];
    if path == nil && !name_str.rsplit_once('.').is_some() {
        // UIKit accepts extensionless image names and resolves common image
        // resources such as "Foo" -> "Foo.png".
        for extension in ["png", "jpg", "jpeg"] {
            let extension = get_static_str(env, extension);
            path = msg![env; bundle pathForResource:name ofType:extension];
            if path != nil {
                break;
            }
        }
    }
    if path == nil
        && (bundle_id.starts_with("com.playforge.ZombieFarm")
            || bundle_id.starts_with("com.playforge.ZFR"))
    {
        if let Some(alias) = zombie_farm_image_alias(&name_str) {
            let alias = ns_string::from_rust_string(env, alias.to_string());
            autorelease(env, alias);
            path = msg![env; bundle pathForResource:alias ofType:nil];
            if path == nil {
                for extension in ["png", "jpg", "jpeg"] {
                    let extension = get_static_str(env, extension);
                    path = msg![env; bundle pathForResource:alias ofType:extension];
                    if path != nil {
                        break;
                    }
                }
            }
            if path != nil {
                log_dbg!(
                    "ZombieFarm image alias: {:?} -> {:?}",
                    name_str,
                    ns_string::to_rust_string(env, alias),
                );
            }
        }
    }
    if path == nil {
        log!("Warning: [UIImage imageNamed:{:?}] => nil", name_str);
        return nil;
    }
    // TODO: find a better eviction policy
    if State::get(env).cached_images.len() > CACHE_SIZE {
        let cache = std::mem::take(&mut State::get_mut(env).cached_images);
        log_dbg!("Evicting {} images from UIImage cache.", cache.len());
        for (_, img) in cache {
            release(env, img);
        }
    }
    if !State::get(env).cached_images.contains_key(&name_str) {
        let img = msg![env; this imageWithContentsOfFile:path];
        retain(env, img);
        State::get_mut(env).cached_images.insert(name_str.clone(), img);
    }
    *State::get(env).cached_images.get(&name_str).unwrap()
}

+ (id)imageWithContentsOfFile:(id)path { // NSString*
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithContentsOfFile:path];
    autorelease(env, new)
}

+ (id)imageWithData:(id)data { // NSData*
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithData:data];
    autorelease(env, new)
}

- (())dealloc {
    let &UIImageHostObject { cg_image, .. } = env.objc.borrow(this);
    CGImageRelease(env, cg_image);

    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)initWithCGImage:(CGImageRef)cg_image {
    CGImageRetain(env, cg_image);
    env.objc.borrow_mut::<UIImageHostObject>(this).cg_image = cg_image;
    this
}

- (id)initWithContentsOfFile:(id)path { // NSString*
    if path == nil {
        return nil;
    }
    let path = ns_string::to_rust_string(env, path); // TODO: avoid copy
    let Ok(bytes) = env.fs.read(GuestPath::new(&path)) else {
        log!("Warning: couldn't read image file at {:?}, returning nil", path);
        release(env, this);
        return nil;
    };
    let image = match Image::from_bytes(&bytes) {
        Ok(image) => image,
        Err(err) => {
            log!(
                "Warning: couldn't decode image file at {:?}: {}, returning nil",
                path,
                err,
            );
            release(env, this);
            return nil;
        }
    };
    let cg_image = cg_image::from_image(env, image);
    env.objc.borrow_mut::<UIImageHostObject>(this).cg_image = cg_image;
    this
}

- (id)initWithData:(id)data { // NSData*
    let slice = ns_data::to_rust_slice(env, data);
    // TODO: refactor common parts
    let image = match Image::from_bytes(slice) {
        Ok(image) => image,
        Err(err) => {
            log!(
                "Warning: couldn't decode image data ({} bytes): {}, returning nil",
                slice.len(),
                err,
            );
            release(env, this);
            return nil;
        }
    };
    let cg_image = cg_image::from_image(env, image);
    env.objc.borrow_mut::<UIImageHostObject>(this).cg_image = cg_image;
    this
}

- (id)stretchableImageWithLeftCapWidth:(NSInteger)_leftCapWidth
                          topCapHeight:(NSInteger)_topCapHeight {
    let new: id = msg_class![env; UIImage alloc];
    let cg_image = env.objc.borrow::<UIImageHostObject>(this).cg_image;
    let new: id = msg![env; new initWithCGImage:cg_image];
    env.objc.borrow_mut::<UIImageHostObject>(new).stretch_caps =
        Some((_leftCapWidth.max(0), _topCapHeight.max(0)));
    autorelease(env, new)
}

// TODO: more init methods
// TODO: more accessors

- (CGImageRef)CGImage {
    env.objc.borrow::<UIImageHostObject>(this).cg_image
}

// TODO: should have UIImageOrientation type
- (NSInteger)imageOrientation {
    // FIXME: load image orientation info from file?
    0 // UIImageOrientationUp
}

- (CGSize)size {
    let image = env.objc.borrow::<UIImageHostObject>(this).cg_image;
    let (width, height) = cg_image::borrow_image(&env.objc, image).dimensions();
    CGSize {
        width: width as _,
        height: height as _,
    }
}

- (CGFloat)scale {
    // TODO: support other scales, such as @2x
    1.0
}

- (())drawInRect:(CGRect)rect {
    let context = UIGraphicsGetCurrentContext(env);
    draw_image_in_rect(env, this, rect, context);
}

- (())drawAtPoint:(CGPoint)point {
    let context = UIGraphicsGetCurrentContext(env);
    if context == nil {
        log!("Warning: [(UIImage*){:?} drawAtPoint:{:?}] is called with nil context, ignoring.", this, point);
        return;
    }
    let image = env.objc.borrow::<UIImageHostObject>(this).cg_image;
    let rect = CGRect {
        origin: point,
        size: CGSize {
            width: CGImageGetWidth(env, image) as CGFloat,
            height: CGImageGetHeight(env, image) as CGFloat,
        }
    };
    draw_image_in_rect(env, this, rect, context);
}

- (bool)_touchHLEIsStretchable {
    env.objc.borrow::<UIImageHostObject>(this).stretch_caps.is_some()
}

@end

// Undocumented class used in NIBs
// TODO: It's not clear _why_ placeholder is needed?
@implementation UIImageNibPlaceholder: UIImage

// NSCoding implementation
- (id)initWithCoder:(id)coder {
    release(env, this);

    // TODO: decode other attributes
    let key_ns_string = get_static_str(env, "UIResourceName");
    let resource_name: id = msg![env; coder decodeObjectForKey:key_ns_string];

    let res = msg_class![env; UIImage imageNamed:resource_name];
    // TODO: It is not clear if we need to additionally retain here?
    retain(env, res)
}

@end

};

fn draw_image_slice(
    env: &mut Environment,
    context: id,
    image: CGImageRef,
    src: CGRect,
    dst: CGRect,
) {
    if src.size.width <= 0.0
        || src.size.height <= 0.0
        || dst.size.width <= 0.0
        || dst.size.height <= 0.0
    {
        return;
    }
    let slice = CGImageCreateWithImageInRect(env, image, src);
    if slice == nil {
        return;
    }
    CGContextDrawImage(env, context, dst, slice);
    CGImageRelease(env, slice);
}

fn draw_image_in_rect(env: &mut Environment, image_obj: id, rect: CGRect, context: id) {
    let host = env.objc.borrow::<UIImageHostObject>(image_obj);
    let image = host.cg_image;
    let stretch_caps = host.stretch_caps;
    CGContextSaveGState(env, context);
    CGContextTranslateCTM(env, context, 0.0, rect.origin.y * 2.0 + rect.size.height);
    CGContextScaleCTM(env, context, 1.0, -1.0);

    if stretch_caps.is_none() {
        CGContextDrawImage(env, context, rect, image);
        CGContextRestoreGState(env, context);
        return;
    }

    let (image_width, image_height) = cg_image::borrow_image(&env.objc, image).dimensions();
    let image_width = image_width as CGFloat;
    let image_height = image_height as CGFloat;
    let (left_cap_width, top_cap_height) = stretch_caps.unwrap();

    let left_src = (left_cap_width as CGFloat).clamp(0.0, image_width);
    let top_src = (top_cap_height as CGFloat).clamp(0.0, image_height);
    let center_src_w = if left_src < image_width { 1.0 } else { 0.0 };
    let center_src_h = if top_src < image_height { 1.0 } else { 0.0 };
    let right_src = (image_width - left_src - center_src_w).max(0.0);
    let bottom_src = (image_height - top_src - center_src_h).max(0.0);

    let left_dst = left_src.min(rect.size.width);
    let top_dst = top_src.min(rect.size.height);
    let right_dst = right_src.min((rect.size.width - left_dst).max(0.0));
    let bottom_dst = bottom_src.min((rect.size.height - top_dst).max(0.0));
    let center_dst_w = (rect.size.width - left_dst - right_dst).max(0.0);
    let center_dst_h = (rect.size.height - top_dst - bottom_dst).max(0.0);

    let src_x = [0.0, left_src, left_src + center_src_w];
    let src_y = [0.0, top_src, top_src + center_src_h];
    let src_w = [left_src, center_src_w, right_src];
    let src_h = [top_src, center_src_h, bottom_src];

    let dst_x = [
        rect.origin.x,
        rect.origin.x + left_dst,
        rect.origin.x + left_dst + center_dst_w,
    ];
    let dst_y = [
        rect.origin.y,
        rect.origin.y + top_dst,
        rect.origin.y + top_dst + center_dst_h,
    ];
    let dst_w = [left_dst, center_dst_w, right_dst];
    let dst_h = [top_dst, center_dst_h, bottom_dst];

    for row in 0..3 {
        for col in 0..3 {
            draw_image_slice(
                env,
                context,
                image,
                CGRect {
                    origin: CGPoint {
                        x: src_x[col],
                        y: src_y[row],
                    },
                    size: CGSize {
                        width: src_w[col],
                        height: src_h[row],
                    },
                },
                CGRect {
                    origin: CGPoint {
                        x: dst_x[col],
                        y: dst_y[row],
                    },
                    size: CGSize {
                        width: dst_w[col],
                        height: dst_h[row],
                    },
                },
            );
        }
    }
    CGContextRestoreGState(env, context);
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(UIImageJPEGRepresentation(_, _)),
    export_c_func!(UIImagePNGRepresentation(_)),
];
