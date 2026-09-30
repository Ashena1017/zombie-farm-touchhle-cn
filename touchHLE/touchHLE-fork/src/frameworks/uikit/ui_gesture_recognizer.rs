/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIGestureRecognizer` and subclasses.

use crate::frameworks::foundation::NSUInteger;
use crate::objc::{
    id, msg, nil, objc_classes, release, retain, ClassExports, HostObject, NSZonePtr, SEL,
};

#[derive(Copy, Clone)]
struct GestureTarget {
    target: id,
    action: SEL,
}

struct UIGestureRecognizerHostObject {
    view: id,
    enabled: bool,
    cancels_touches_in_view: bool,
    delays_touches_began: bool,
    delays_touches_ended: bool,
    state: NSInteger,
    targets: Vec<GestureTarget>,
    number_of_taps_required: NSUInteger,
    number_of_touches_required: NSUInteger,
}
impl HostObject for UIGestureRecognizerHostObject {}

use crate::frameworks::foundation::NSInteger;

impl Default for UIGestureRecognizerHostObject {
    fn default() -> Self {
        Self {
            view: nil,
            enabled: true,
            cancels_touches_in_view: true,
            delays_touches_began: false,
            delays_touches_ended: true,
            state: 0,
            targets: Vec::new(),
            number_of_taps_required: 1,
            number_of_touches_required: 1,
        }
    }
}

pub fn set_view(env: &mut crate::Environment, recognizer: id, view: id) {
    if recognizer == nil {
        return;
    }
    env.objc
        .borrow_mut::<UIGestureRecognizerHostObject>(recognizer)
        .view = view;
}

fn add_target(env: &mut crate::Environment, this: id, target: id, action: SEL) {
    if target == nil || action.is_null() {
        return;
    }

    retain(env, target);
    env.objc
        .borrow_mut::<UIGestureRecognizerHostObject>(this)
        .targets
        .push(GestureTarget { target, action });
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIGestureRecognizer: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(
        this,
        Box::<UIGestureRecognizerHostObject>::default(),
        &mut env.mem,
    )
}

- (())dealloc {
    let UIGestureRecognizerHostObject {
        view: _,
        enabled: _,
        cancels_touches_in_view: _,
        delays_touches_began: _,
        delays_touches_ended: _,
        state: _,
        targets,
        number_of_taps_required: _,
        number_of_touches_required: _,
    } = std::mem::take(env.objc.borrow_mut(this));

    for target in targets {
        release(env, target.target);
    }

    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)initWithTarget:(id)target action:(SEL)action {
    let this: id = msg![env; this init];
    add_target(env, this, target, action);
    this
}

- (())addTarget:(id)target action:(SEL)action {
    add_target(env, this, target, action);
}

- (())removeTarget:(id)target action:(SEL)action {
    let mut removed_targets = Vec::new();
    {
        let targets = &mut env.objc
            .borrow_mut::<UIGestureRecognizerHostObject>(this)
            .targets;
        let mut idx = 0;
        while idx < targets.len() {
            let gesture_target = targets[idx];
            let target_matches = target == nil || target == gesture_target.target;
            let action_matches = action.is_null() || action == gesture_target.action;
            if target_matches && action_matches {
                removed_targets.push(targets.remove(idx).target);
            } else {
                idx += 1;
            }
        }
    }
    for target in removed_targets {
        release(env, target);
    }
}

- (id)view {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).view
}

- (bool)isEnabled {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).enabled
}

- (())setEnabled:(bool)enabled {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).enabled = enabled;
}

- (bool)cancelsTouchesInView {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).cancels_touches_in_view
}

- (())setCancelsTouchesInView:(bool)cancels {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).cancels_touches_in_view = cancels;
}

- (bool)delaysTouchesBegan {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).delays_touches_began
}

- (())setDelaysTouchesBegan:(bool)delays {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).delays_touches_began = delays;
}

- (bool)delaysTouchesEnded {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).delays_touches_ended
}

- (())setDelaysTouchesEnded:(bool)delays {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).delays_touches_ended = delays;
}

- (NSInteger)state {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).state
}

- (())setDelegate:(id)_delegate {
}

- (id)delegate {
    nil
}

@end

@implementation UITapGestureRecognizer: UIGestureRecognizer

- (NSUInteger)numberOfTapsRequired {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).number_of_taps_required
}

- (())setNumberOfTapsRequired:(NSUInteger)taps {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).number_of_taps_required = taps;
}

- (NSUInteger)numberOfTouchesRequired {
    env.objc.borrow::<UIGestureRecognizerHostObject>(this).number_of_touches_required
}

- (())setNumberOfTouchesRequired:(NSUInteger)touches {
    env.objc.borrow_mut::<UIGestureRecognizerHostObject>(this).number_of_touches_required = touches;
}

@end

};
