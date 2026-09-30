/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIButton`.

use super::{UIControlState, UIControlStateNormal};
use crate::abi::{impl_GuestRet_for_large_struct, GuestArg};
use crate::frameworks::core_graphics::{CGFloat, CGPoint, CGRect};
use crate::frameworks::foundation::ns_string::{from_rust_string, get_static_str, to_rust_string};
use crate::frameworks::foundation::{NSInteger, NSUInteger};
use crate::frameworks::uikit::ui_font::UITextAlignmentCenter;
use crate::mem::SafeRead;
use crate::objc::{
    autorelease, id, impl_HostObject_with_superclass, msg, msg_class, msg_super, nil, objc_classes,
    release, retain, todo_objc_setter, ClassExports, HostObject, NSZonePtr,
};
use crate::Environment;
use std::collections::HashMap;

type UIButtonType = NSInteger;
pub const UIButtonTypeCustom: UIButtonType = 0;
pub const UIButtonTypeRoundedRect: UIButtonType = 1;
#[allow(dead_code)]
const UIButtonTypeDetailDisclosure: UIButtonType = 2;
#[allow(dead_code)]
const UIButtonTypeInfoLight: UIButtonType = 3;
#[allow(dead_code)]
const UIButtonTypeInfoDark: UIButtonType = 4;
#[allow(dead_code)]
const UIButtonTypeContactAdd: UIButtonType = 5;

#[derive(Copy, Clone, Debug, Default)]
#[repr(C, packed)]
struct UIEdgeInsets {
    top: CGFloat,
    left: CGFloat,
    bottom: CGFloat,
    right: CGFloat,
}
unsafe impl SafeRead for UIEdgeInsets {}
impl_GuestRet_for_large_struct!(UIEdgeInsets);
impl GuestArg for UIEdgeInsets {
    const REG_COUNT: usize = 4;

    fn from_regs(regs: &[u32]) -> Self {
        UIEdgeInsets {
            top: GuestArg::from_regs(&regs[0..1]),
            left: GuestArg::from_regs(&regs[1..2]),
            bottom: GuestArg::from_regs(&regs[2..3]),
            right: GuestArg::from_regs(&regs[3..4]),
        }
    }

    fn to_regs(self, regs: &mut [u32]) {
        self.top.to_regs(&mut regs[0..1]);
        self.left.to_regs(&mut regs[1..2]);
        self.bottom.to_regs(&mut regs[2..3]);
        self.right.to_regs(&mut regs[3..4]);
    }
}

// Host object for an intermediate object
// used for decoding of UIButton from a NIB
#[derive(Default)]
struct UIButtonContentHostObject {
    /// `NSString*`
    title: id,
    /// `UIColor*`
    title_color: id,
    /// `UIImage*`
    image: id,
    /// `UIImage*`
    background_image: id,
}
impl HostObject for UIButtonContentHostObject {}

pub struct UIButtonHostObject {
    superclass: super::UIControlHostObject,
    type_: UIButtonType,
    /// `UILabel*`
    title_label: id,
    /// `UIImageView*`
    image_view: id,
    /// `UIImageView*`
    background_image_view: id,
    /// Values are `UIString*`
    titles_for_states: HashMap<UIControlState, id>,
    /// Values are `UIColor*`
    title_colors_for_states: HashMap<UIControlState, id>,
    /// Values are `UIImage*`
    images_for_states: HashMap<UIControlState, id>,
    /// Values are `UIImage*`
    background_images_for_states: HashMap<UIControlState, id>,
    title_edge_insets: UIEdgeInsets,
    image_edge_insets: UIEdgeInsets,
    content_edge_insets: UIEdgeInsets,
}
impl_HostObject_with_superclass!(UIButtonHostObject);
impl Default for UIButtonHostObject {
    fn default() -> Self {
        UIButtonHostObject {
            superclass: Default::default(),
            type_: UIButtonTypeCustom,
            title_label: nil,
            image_view: nil,
            background_image_view: nil,
            titles_for_states: HashMap::new(),
            title_colors_for_states: HashMap::new(),
            images_for_states: HashMap::new(),
            background_images_for_states: HashMap::new(),
            title_edge_insets: Default::default(),
            image_edge_insets: Default::default(),
            content_edge_insets: Default::default(),
        }
    }
}

fn update(env: &mut Environment, this: id) {
    let title_label: id = msg![env; this titleLabel];
    let title: id = msg![env; this currentTitle];
    () = msg![env; title_label setText:title];
    let title_color: id = msg![env; this currentTitleColor];
    () = msg![env; title_label setTextColor:title_color];

    let image_view: id = msg![env; this imageView];
    let image: id = msg![env; this currentImage];
    () = msg![env; image_view setImage:image];

    let background_image_view: id = msg![env; this backgroundImageView];
    let background_image: id = msg![env; this currentBackgroundImage];
    () = msg![env; background_image_view setImage:background_image];
}

fn init_common(env: &mut Environment, this: id) -> id {
    () = msg![env; this setOpaque:false];
    let bg_color: id = msg_class![env; UIColor clearColor];

    let title_label: id = msg_class![env; UILabel new];
    () = msg![env; title_label setBackgroundColor:bg_color];
    () = msg![env; title_label setTextAlignment:UITextAlignmentCenter];

    let text_color: id = msg_class![env; UIColor whiteColor];

    let image_view: id = msg_class![env; UIImageView new];
    let background_image_view: id = msg_class![env; UIImageView new];

    let host_obj = env.objc.borrow_mut::<UIButtonHostObject>(this);
    host_obj.title_label = title_label;
    host_obj.image_view = image_view;
    host_obj.background_image_view = background_image_view;
    host_obj.titles_for_states.insert(UIControlStateNormal, nil);
    host_obj
        .title_colors_for_states
        .insert(UIControlStateNormal, text_color);
    host_obj.images_for_states.insert(UIControlStateNormal, nil);
    host_obj
        .background_images_for_states
        .insert(UIControlStateNormal, nil);

    () = msg![env; this addSubview:background_image_view];
    () = msg![env; this addSubview:title_label];
    () = msg![env; this addSubview:image_view];
    update(env, this);
    () = msg![env; this setNeedsLayout];

    this
}
// TODO: refactor this to be a part of common init
fn set_type(env: &mut Environment, button: id, type_: UIButtonType) {
    match type_ {
        UIButtonTypeCustom => (),
        UIButtonTypeRoundedRect => {
            let bg_color: id = msg_class![env; UIColor whiteColor];
            // TODO: set blue background image in highlighted state
            // TODO: image highlighting?
            () = msg![env; button setBackgroundColor:bg_color];
            // On the real iPhone OS, this is a semi-dark, desaturated blue.
            // Should we match it?
            let text_color: id = msg_class![env; UIColor blackColor];
            () = msg![env; button setTitleColor:text_color
                                       forState:UIControlStateNormal];
            let layer: id = msg![env; button layer];
            () = msg![env; layer setCornerRadius:(10.0 as CGFloat)];
            // TODO: set border, once supported
        }
        _ => {
            log!("TODO: UIButtonType {}", type_);
        }
    }
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIButton: UIControl

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UIButtonHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)buttonWithType:(UIButtonType)type_ {
    let button: id = msg![env; this new];
    set_type(env, button, type_);
    autorelease(env, button)
}

- (id)initWithFrame:(CGRect)frame {
    let this: id = msg_super![env; this initWithFrame:frame];

    let bg_color: id = msg_class![env; UIColor clearColor];
    () = msg![env; this setBackgroundColor:bg_color];

    let this: id = init_common(env, this);
    // TODO: check which type is a default one
    set_type(env, this, UIButtonTypeCustom);
    this
}

- (id)initWithCoder:(id)coder {
    let this: id = msg_super![env; this initWithCoder:coder];

    let this = init_common(env, this);

    let key_ns_string = get_static_str(env, "UIButtonType");
    let type_: i32 = msg![env; coder decodeIntForKey:key_ns_string];
    set_type(env, this, type_);

    let key_ns_string = get_static_str(env, "UIButtonStatefulContent");
    let dict: id = msg![env; coder decodeObjectForKey:key_ns_string];
    assert!(dict != nil);
    log_dbg!("UIButtonStatefulContent dict: {}", {
        let desc: id = msg![env; dict description];
        to_rust_string(env, desc)
    });

    // It's not entirely clear how the state information is encoded
    // in this dict.
    // TODO: support decoding properties of other states
    let key_idx: id = msg_class![env; NSNumber numberWithLongLong:0i64];
    let mut button_content: id = msg![env; dict objectForKey:key_idx];
    if button_content == nil {
        let values: id = msg![env; dict allValues];
        let value_count: NSUInteger = msg![env; values count];
        if value_count != 0 {
            button_content = msg![env; values objectAtIndex:0u32];
            log!("UIButton initWithCoder: no state 0 content, falling back to first stateful value");
        }
    }
    let bundle_id = env.bundle.bundle_identifier().to_string();
    if bundle_id.starts_with("com.playforge.ZombieFarm")
        || bundle_id.starts_with("com.playforge.ZFR")
    {
        if button_content != nil {
            let desc: id = msg![env; button_content description];
            log!("ZombieFarm UIButton content: {}", to_rust_string(env, desc));
        } else {
            log!("ZombieFarm UIButton content: nil");
        }
    }

    let title: id = msg![env; button_content title];
    if title != nil {
        log_dbg!("UIButton initWithCoder: title {}", to_rust_string(env, title));
        () = msg![env; this setTitle:title forState:UIControlStateNormal];
    }

    let title_color: id = msg![env; button_content titleColor];
    if title_color != nil {
        log_dbg!("UIButton initWithCoder: title_color {}", to_rust_string(env, title_color));
        () = msg![env; this setTitleColor:title_color forState:UIControlStateNormal];
    }

    let image: id = msg![env; button_content image];
    if image != nil {
        log_dbg!("UIButton initWithCoder: found normal-state image {:?}", image);
        () = msg![env; this setImage:image forState:UIControlStateNormal];
    }

    let background_image: id = msg![env; button_content backgroundImage];
    if background_image != nil {
        log_dbg!(
            "UIButton initWithCoder: found normal-state background image {:?}",
            background_image
        );
        () = msg![env; this setBackgroundImage:background_image
                                   forState:UIControlStateNormal];
    }

    update(env, this);

    this
}

- (())dealloc {
    let UIButtonHostObject {
        superclass: _,
        type_: _,
        title_label,
        image_view,
        background_image_view,
        titles_for_states,
        title_colors_for_states,
        images_for_states,
        background_images_for_states,
        title_edge_insets: _,
        image_edge_insets: _,
        content_edge_insets: _,
    } = std::mem::take(env.objc.borrow_mut(this));

    release(env, title_label);
    release(env, image_view);
    release(env, background_image_view);
    for (_state, title) in titles_for_states {
        release(env, title);
    }
    for (_state, color) in title_colors_for_states {
        release(env, color);
    }
    for (_state, image) in images_for_states {
        release(env, image);
    }
    for (_state, background_image) in background_images_for_states {
        release(env, background_image);
    }
    msg_super![env; this dealloc]
}

- (())layoutSubviews {
    let host_obj = env.objc.borrow::<UIButtonHostObject>(this);
    let label = host_obj.title_label;
    let image_view = host_obj.image_view;
    let background_image_view = host_obj.background_image_view;
    let title_edge_insets = host_obj.title_edge_insets;
    let image_edge_insets = host_obj.image_edge_insets;
    let bounds: CGRect = msg![env; this bounds];

    () = msg![env; background_image_view setFrame:bounds];
    let label_frame = CGRect {
        origin: CGPoint {
            x: bounds.origin.x + title_edge_insets.left,
            y: bounds.origin.y + title_edge_insets.top,
        },
        size: crate::frameworks::core_graphics::CGSize {
            width: (bounds.size.width - title_edge_insets.left - title_edge_insets.right).max(0.0),
            height: (bounds.size.height - title_edge_insets.top - title_edge_insets.bottom).max(0.0),
        },
    };
    () = msg![env; label setFrame:label_frame];
    let image_frame = CGRect {
        origin: CGPoint {
            x: bounds.origin.x + image_edge_insets.left,
            y: bounds.origin.y + image_edge_insets.top,
        },
        size: crate::frameworks::core_graphics::CGSize {
            width: (bounds.size.width - image_edge_insets.left - image_edge_insets.right).max(0.0),
            height: (bounds.size.height - image_edge_insets.top - image_edge_insets.bottom).max(0.0),
        },
    };
    () = msg![env; image_view setFrame:image_frame];

}

- (UIButtonType)buttonType {
    env.objc.borrow_mut::<UIButtonHostObject>(this).type_
}

- (id)titleLabel {
    env.objc.borrow_mut::<UIButtonHostObject>(this).title_label
}

- (id)imageView {
    env.objc.borrow_mut::<UIButtonHostObject>(this).image_view
}

- (id)backgroundImageView {
    env.objc.borrow_mut::<UIButtonHostObject>(this).background_image_view
}
- (())setEnabled:(bool)enabled {
    () = msg_super![env; this setEnabled:enabled];
    update(env, this);
}
- (())setSelected:(bool)selected {
    () = msg_super![env; this setSelected:selected];
    update(env, this);
}
- (())setHighlighted:(bool)highlighted {
    () = msg_super![env; this setHighlighted:highlighted];
    update(env, this);
}
- (())setAdjustsImageWhenHighlighted:(bool)adjusts {
    todo_objc_setter!(this, adjusts);
}
- (())setShowsTouchWhenHighlighted:(bool)shows {
    todo_objc_setter!(this, shows);
}
- (UIEdgeInsets)titleEdgeInsets {
    env.objc.borrow::<UIButtonHostObject>(this).title_edge_insets
}
- (())setTitleEdgeInsets:(UIEdgeInsets)insets {
    env.objc.borrow_mut::<UIButtonHostObject>(this).title_edge_insets = insets;
    () = msg![env; this setNeedsLayout];
}
- (UIEdgeInsets)imageEdgeInsets {
    env.objc.borrow::<UIButtonHostObject>(this).image_edge_insets
}
- (())setImageEdgeInsets:(UIEdgeInsets)insets {
    env.objc.borrow_mut::<UIButtonHostObject>(this).image_edge_insets = insets;
    () = msg![env; this setNeedsLayout];
}
- (UIEdgeInsets)contentEdgeInsets {
    env.objc.borrow::<UIButtonHostObject>(this).content_edge_insets
}
- (())setContentEdgeInsets:(UIEdgeInsets)insets {
    env.objc.borrow_mut::<UIButtonHostObject>(this).content_edge_insets = insets;
    () = msg![env; this setNeedsLayout];
}
- (())setFont:(id)font { // UIFont*
    let label = env.objc.borrow_mut::<UIButtonHostObject>(this).title_label;
    () = msg![env; label setFont:font];
    update(env, this);
}
// TODO: observe focussing somehow

- (id)currentTitle {
    let state: UIControlState = msg![env; this state];
    msg![env; this titleForState:state]
}
- (id)titleForState:(UIControlState)state {
    let host_obj = env.objc.borrow::<UIButtonHostObject>(this);
    host_obj.titles_for_states.get(&state).or_else(|| {
        host_obj.titles_for_states.get(&UIControlStateNormal)
    }).copied().unwrap()
}
- (())setTitle:(id)title // NSString*
      forState:(UIControlState)state {
    retain(env, title);
    let host_obj = env.objc.borrow_mut::<UIButtonHostObject>(this);
    if let Some(old) = host_obj.titles_for_states.insert(state, title) {
        release(env, old);
    }
    update(env, this);
}

- (id)currentBackgroundImage {
    let state: UIControlState = msg![env; this state];
    msg![env; this backgroundImageForState:state]
}
- (id)backgroundImageForState:(UIControlState)state {
    let host_obj = env.objc.borrow::<UIButtonHostObject>(this);
    host_obj.background_images_for_states.get(&state).or_else(|| {
        host_obj.background_images_for_states.get(&UIControlStateNormal)
    }).copied().unwrap()
}
- (())setBackgroundImage:(id)image forState:(UIControlState)state {
    retain(env,image);
    let host_obj = env.objc.borrow_mut::<UIButtonHostObject>(this);
    if let Some(old) = host_obj.background_images_for_states.insert(state, image) {
        release(env, old);
    }
    update(env, this);
}

- (id)currentTitleColor {
    let state: UIControlState = msg![env; this state];
    msg![env; this titleColorForState:state]
}
- (id)titleColorForState:(UIControlState)state {
    let host_obj = env.objc.borrow::<UIButtonHostObject>(this);
    host_obj.title_colors_for_states.get(&state).or_else(|| {
        host_obj.title_colors_for_states.get(&UIControlStateNormal)
    }).copied().unwrap()
}
- (())setTitleColor:(id)color // UIColor*
      forState:(UIControlState)state {
    retain(env, color);
    let host_obj = env.objc.borrow_mut::<UIButtonHostObject>(this);
    if let Some(old) = host_obj.title_colors_for_states.insert(state, color) {
        release(env, old);
    }
    update(env, this);
}

- (id)currentImage {
    let state: UIControlState = msg![env; this state];
    msg![env; this imageForState:state]
}
- (id)imageForState:(UIControlState)state {
    let host_obj = env.objc.borrow::<UIButtonHostObject>(this);
    host_obj.images_for_states.get(&state).or_else(|| {
        host_obj.images_for_states.get(&UIControlStateNormal)
    }).copied().unwrap()
}
- (())setImage:(id)image // UIImage*
      forState:(UIControlState)state {
    retain(env, image);
    let host_obj = env.objc.borrow_mut::<UIButtonHostObject>(this);
    if let Some(old) = host_obj.images_for_states.insert(state, image) {
        release(env, old);
    }
    update(env, this);
}

// TODO: actions, etc

- (id)hitTest:(CGPoint)point
    withEvent:(id)event { // UIEvent* (possibly nil)
    // Hide subviews from hit testing so event goes straight to this control
    if msg![env; this pointInside:point withEvent:event] {
        this
    } else {
        nil
    }
}

@end

// Undocumented classes used by NIBs

@implementation UIRoundedRectButton: UIButton
// TODO: rendering of round corners
@end

@implementation UIButtonContent: NSObject

+ (id)alloc {
    let host_object = Box::<UIButtonContentHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

// NSCoding implementation
- (id)initWithCoder:(id)coder {
    let title_key = get_static_str(env, "UITitle");
    let title: id = msg![env; coder decodeObjectForKey:title_key];
    log_dbg!("UIButtonContent: UITitle -> {}", to_rust_string(env, title));

    let title_color_key = get_static_str(env, "UITitleColor");
    let title_color: id = msg![env; coder decodeObjectForKey:title_color_key];
    log_dbg!("UIButtonContent: UITitleColor -> {:?}", title_color);

    let image_key = get_static_str(env, "UIImage");
    let image: id = msg![env; coder decodeObjectForKey:image_key];
    log_dbg!("UIButtonContent: UIImage -> {:?}", image);

    let background_image_key = get_static_str(env, "UIBackgroundImage");
    let background_image: id = msg![env; coder decodeObjectForKey:background_image_key];
    log_dbg!("UIButtonContent: UIBackgroundImage -> {:?}", background_image);

    retain(env, title);
    retain(env, title_color);
    retain(env, image);
    retain(env, background_image);
    let host_obj = env.objc.borrow_mut::<UIButtonContentHostObject>(this);
    host_obj.title = title;
    host_obj.title_color = title_color;
    host_obj.image = image;
    host_obj.background_image = background_image;

    this
}

- (id)title {
    env.objc.borrow::<UIButtonContentHostObject>(this).title
}
- (id)titleColor {
    env.objc.borrow::<UIButtonContentHostObject>(this).title_color
}
- (id)image {
    env.objc.borrow::<UIButtonContentHostObject>(this).image
}
- (id)backgroundImage {
    env.objc.borrow::<UIButtonContentHostObject>(this).background_image
}

- (id)description {
    let title = env.objc.borrow::<UIButtonContentHostObject>(this).title;
    let title_color = env.objc.borrow::<UIButtonContentHostObject>(this).title_color;
    let image = env.objc.borrow::<UIButtonContentHostObject>(this).image;
    let background_image = env.objc.borrow::<UIButtonContentHostObject>(this).background_image;
    let desc_str = format!(
        "UIButtonContent({this:?}, title {title:?}, title_color {title_color:?}, image {image:?}, background_image {background_image:?})"
    );
    let desc = from_rust_string(env, desc_str);
    autorelease(env, desc)
}

- (())dealloc {
    let &UIButtonContentHostObject {
        title,
        title_color,
        image,
        background_image,
    } = env.objc.borrow(this);
    release(env, title);
    release(env, title_color);
    release(env, image);
    release(env, background_image);

    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};
