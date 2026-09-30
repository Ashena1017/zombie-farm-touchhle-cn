/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UISlider`.

use crate::environment::Environment;
use crate::frameworks::core_graphics::{CGFloat, CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_string::get_static_str;
use crate::frameworks::foundation::NSUInteger;
use crate::frameworks::uikit::ui_view::ui_control::{send_actions, UIControlEventValueChanged};
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_class, msg_super, nil, objc_classes, release,
    ClassExports, NSZonePtr,
};

const DEFAULT_WIDTH: CGFloat = 118.0;
const DEFAULT_HEIGHT: CGFloat = 23.0;
const TRACK_HEIGHT: CGFloat = 4.0;
const THUMB_SIZE: CGFloat = 20.0;

pub struct UISliderHostObject {
    superclass: super::UIControlHostObject,
    value: f32,
    minimum_value: f32,
    maximum_value: f32,
    continuous: bool,
    /// `UIView*`
    track: id,
    /// `UIView*`
    filled_track: id,
    /// `UIView*`
    thumb: id,
    /// `UIImage*`, retained by the app or nib graph; stored weakly.
    minimum_value_image: id,
    /// `UIImage*`, retained by the app or nib graph; stored weakly.
    maximum_value_image: id,
}
impl_HostObject_with_superclass!(UISliderHostObject);
impl Default for UISliderHostObject {
    fn default() -> Self {
        UISliderHostObject {
            superclass: Default::default(),
            value: 0.0,
            minimum_value: 0.0,
            maximum_value: 1.0,
            continuous: true,
            track: nil,
            filled_track: nil,
            thumb: nil,
            minimum_value_image: nil,
            maximum_value_image: nil,
        }
    }
}

fn clamp_value(value: f32, minimum_value: f32, maximum_value: f32) -> f32 {
    if maximum_value <= minimum_value {
        return minimum_value;
    }
    value.clamp(minimum_value, maximum_value)
}

fn fraction_for_value(value: f32, minimum_value: f32, maximum_value: f32) -> f32 {
    if maximum_value <= minimum_value {
        0.0
    } else {
        ((value - minimum_value) / (maximum_value - minimum_value)).clamp(0.0, 1.0)
    }
}

fn update(env: &mut Environment, this: id) {
    let (track, filled_track, thumb, value, minimum_value, maximum_value) = {
        let host_obj = env.objc.borrow::<UISliderHostObject>(this);
        (
            host_obj.track,
            host_obj.filled_track,
            host_obj.thumb,
            host_obj.value,
            host_obj.minimum_value,
            host_obj.maximum_value,
        )
    };
    if track == nil || filled_track == nil || thumb == nil {
        return;
    }

    let bounds: CGRect = msg![env; this bounds];
    let fraction = fraction_for_value(value, minimum_value, maximum_value);
    let usable_width = (bounds.size.width - THUMB_SIZE).max(0.0);
    let thumb_x = bounds.origin.x + fraction * usable_width;
    let track_x = bounds.origin.x + THUMB_SIZE / 2.0;
    let track_y = bounds.origin.y + (bounds.size.height - TRACK_HEIGHT) / 2.0;
    let track_width = usable_width;

    let track_rect = CGRect {
        origin: CGPoint {
            x: track_x,
            y: track_y,
        },
        size: CGSize {
            width: track_width,
            height: TRACK_HEIGHT,
        },
    };
    let filled_rect = CGRect {
        origin: track_rect.origin,
        size: CGSize {
            width: track_width * fraction,
            height: TRACK_HEIGHT,
        },
    };
    let thumb_rect = CGRect {
        origin: CGPoint {
            x: thumb_x,
            y: bounds.origin.y + (bounds.size.height - THUMB_SIZE) / 2.0,
        },
        size: CGSize {
            width: THUMB_SIZE,
            height: THUMB_SIZE,
        },
    };

    () = msg![env; track setFrame:track_rect];
    () = msg![env; filled_track setFrame:filled_rect];
    () = msg![env; thumb setFrame:thumb_rect];

    fn set_radius(env: &mut Environment, view: id, radius: CGFloat) {
        let layer: id = msg![env; view layer];
        () = msg![env; layer setCornerRadius:radius];
    }
    set_radius(env, track, TRACK_HEIGHT / 2.0);
    set_radius(env, filled_track, TRACK_HEIGHT / 2.0);
    set_radius(env, thumb, THUMB_SIZE / 2.0);
}

fn init_common(env: &mut Environment, this: id) -> id {
    let clear_color: id = msg_class![env; UIColor clearColor];
    let track_color: id = msg_class![env; UIColor colorWithRed:(178.0f32/255.0)
                                                        green:(178.0f32/255.0)
                                                         blue:(178.0f32/255.0)
                                                        alpha:1.0f32];
    let fill_color: id = msg_class![env; UIColor colorWithRed:(65.0f32/255.0)
                                                       green:(132.0f32/255.0)
                                                        blue:(232.0f32/255.0)
                                                       alpha:1.0f32];
    let thumb_color: id = msg_class![env; UIColor whiteColor];

    () = msg![env; this setBackgroundColor:clear_color];

    let track: id = msg_class![env; UIView new];
    () = msg![env; track setBackgroundColor:track_color];

    let filled_track: id = msg_class![env; UIView new];
    () = msg![env; filled_track setBackgroundColor:fill_color];

    let thumb: id = msg_class![env; UIView new];
    () = msg![env; thumb setBackgroundColor:thumb_color];

    let host_obj = env.objc.borrow_mut::<UISliderHostObject>(this);
    host_obj.track = track;
    host_obj.filled_track = filled_track;
    host_obj.thumb = thumb;

    () = msg![env; this addSubview:track];
    () = msg![env; this addSubview:filled_track];
    () = msg![env; this addSubview:thumb];
    update(env, this);

    this
}

fn set_value(env: &mut Environment, this: id, value: f32) {
    let value = {
        let host_obj = env.objc.borrow::<UISliderHostObject>(this);
        clamp_value(value, host_obj.minimum_value, host_obj.maximum_value)
    };
    env.objc.borrow_mut::<UISliderHostObject>(this).value = value;
    update(env, this);
}

fn set_value_from_touch(env: &mut Environment, this: id, touch: id) -> bool {
    let location: CGPoint = msg![env; touch locationInView:this];
    let bounds: CGRect = msg![env; this bounds];
    let (minimum_value, maximum_value, old_value) = {
        let host_obj = env.objc.borrow::<UISliderHostObject>(this);
        (
            host_obj.minimum_value,
            host_obj.maximum_value,
            host_obj.value,
        )
    };
    let usable_width = (bounds.size.width - THUMB_SIZE).max(1.0);
    let fraction =
        ((location.x - bounds.origin.x - THUMB_SIZE / 2.0) / usable_width).clamp(0.0, 1.0);
    let new_value = minimum_value + fraction * (maximum_value - minimum_value);
    set_value(env, this, new_value);
    (new_value - old_value).abs() > f32::EPSILON
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UISlider: UIControl

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UISliderHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (id)initWithFrame:(CGRect)frame {
    let frame = if frame.size.width == 0.0 || frame.size.height == 0.0 {
        CGRect {
            origin: frame.origin,
            size: CGSize {
                width: DEFAULT_WIDTH,
                height: DEFAULT_HEIGHT,
            },
        }
    } else {
        frame
    };
    let this: id = msg_super![env; this initWithFrame:frame];
    init_common(env, this)
}

// NSCoding implementation
- (id)initWithCoder:(id)coder {
    let this: id = msg_super![env; this initWithCoder:coder];
    let this = init_common(env, this);

    let key = get_static_str(env, "UISliderMinValue");
    if msg![env; coder containsValueForKey:key] {
        let value: f32 = msg![env; coder decodeFloatForKey:key];
        () = msg![env; this setMinimumValue:value];
    }

    let key = get_static_str(env, "UISliderMaxValue");
    if msg![env; coder containsValueForKey:key] {
        let value: f32 = msg![env; coder decodeFloatForKey:key];
        () = msg![env; this setMaximumValue:value];
    }

    let key = get_static_str(env, "UISliderValue");
    if msg![env; coder containsValueForKey:key] {
        let value: f32 = msg![env; coder decodeFloatForKey:key];
        () = msg![env; this setValue:value];
    }

    let key = get_static_str(env, "UISliderContinuous");
    if msg![env; coder containsValueForKey:key] {
        let continuous: bool = msg![env; coder decodeBoolForKey:key];
        () = msg![env; this setContinuous:continuous];
    }

    this
}

- (())dealloc {
    let UISliderHostObject {
        superclass: _,
        value: _,
        minimum_value: _,
        maximum_value: _,
        continuous: _,
        track,
        filled_track,
        thumb,
        minimum_value_image: _,
        maximum_value_image: _,
    } = std::mem::take(env.objc.borrow_mut(this));

    release(env, track);
    release(env, filled_track);
    release(env, thumb);
    msg_super![env; this dealloc]
}

- (())layoutSubviews {
    update(env, this);
}

- (f32)value {
    env.objc.borrow::<UISliderHostObject>(this).value
}
- (())setValue:(f32)value {
    msg![env; this setValue:value animated:false]
}
- (())setValue:(f32)value animated:(bool)_animated {
    set_value(env, this, value);
}

- (f32)minimumValue {
    env.objc.borrow::<UISliderHostObject>(this).minimum_value
}
- (())setMinimumValue:(f32)value {
    {
        let host_obj = env.objc.borrow_mut::<UISliderHostObject>(this);
        host_obj.minimum_value = value;
        if host_obj.maximum_value < value {
            host_obj.maximum_value = value;
        }
        host_obj.value = clamp_value(host_obj.value, host_obj.minimum_value, host_obj.maximum_value);
    }
    update(env, this);
}

- (f32)maximumValue {
    env.objc.borrow::<UISliderHostObject>(this).maximum_value
}
- (())setMaximumValue:(f32)value {
    {
        let host_obj = env.objc.borrow_mut::<UISliderHostObject>(this);
        host_obj.maximum_value = value;
        if host_obj.minimum_value > value {
            host_obj.minimum_value = value;
        }
        host_obj.value = clamp_value(host_obj.value, host_obj.minimum_value, host_obj.maximum_value);
    }
    update(env, this);
}

- (bool)isContinuous {
    env.objc.borrow::<UISliderHostObject>(this).continuous
}
- (())setContinuous:(bool)continuous {
    env.objc.borrow_mut::<UISliderHostObject>(this).continuous = continuous;
}

- (())setMinimumValueImage:(id)img { // UIImage *
    env.objc.borrow_mut::<UISliderHostObject>(this).minimum_value_image = img;
}
- (id)minimumValueImage {
    env.objc.borrow::<UISliderHostObject>(this).minimum_value_image
}
- (())setMaximumValueImage:(id)img { // UIImage *
    env.objc.borrow_mut::<UISliderHostObject>(this).maximum_value_image = img;
}
- (id)maximumValueImage {
    env.objc.borrow::<UISliderHostObject>(this).maximum_value_image
}

- (())setThumbImage:(id)_image forState:(NSUInteger)_state {
}
- (())setMinimumTrackImage:(id)_image forState:(NSUInteger)_state {
}
- (())setMaximumTrackImage:(id)_image forState:(NSUInteger)_state {
}

- (id)hitTest:(CGPoint)point
    withEvent:(id)event { // UIEvent* (possibly nil)
    if msg![env; this pointInside:point withEvent:event] {
        this
    } else {
        nil
    }
}

- (bool)beginTrackingWithTouch:(id)touch
                     withEvent:(id)event {
    let changed = set_value_from_touch(env, this, touch);
    if changed && msg![env; this isContinuous] {
        send_actions(env, this, event, UIControlEventValueChanged);
    }
    true
}
- (bool)continueTrackingWithTouch:(id)touch
                        withEvent:(id)event {
    let changed = set_value_from_touch(env, this, touch);
    if changed && msg![env; this isContinuous] {
        send_actions(env, this, event, UIControlEventValueChanged);
    }
    true
}
- (())endTrackingWithTouch:(id)touch
                  withEvent:(id)event {
    let changed = set_value_from_touch(env, this, touch);
    () = msg_super![env; this endTrackingWithTouch:touch withEvent:event];
    if changed || !msg![env; this isContinuous] {
        send_actions(env, this, event, UIControlEventValueChanged);
    }
}

@end

};
