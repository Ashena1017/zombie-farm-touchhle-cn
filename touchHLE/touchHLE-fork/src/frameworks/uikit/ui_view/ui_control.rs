/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIControl`.
//!
//! Useful resources:
//! - The [Target-Action section](https://developer.apple.com/library/archive/documentation/General/Conceptual/CocoaEncyclopedia/Target-Action/Target-Action.html) of Apple's "Concepts in Objective-C Programming".

pub mod ui_button;
pub mod ui_segmented_control;
pub mod ui_slider;
pub mod ui_switch;
pub mod ui_text_field;

use crate::frameworks::core_graphics::CGPoint;
use crate::frameworks::foundation::NSUInteger;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_send, msg_super, nil, objc_classes, release,
    retain, ClassExports, NSZonePtr, ObjC, SEL,
};
use crate::Environment;

// TODO: There are many members of this enum missing.
pub type UIControlEvents = NSUInteger;
const UIControlEventTouchDown: UIControlEvents = 1 << 0;
const UIControlEventTouchDragInside: UIControlEvents = 1 << 2;
const UIControlEventTouchDragOutside: UIControlEvents = 1 << 3;
const UIControlEventTouchDragEnter: UIControlEvents = 1 << 4;
const UIControlEventTouchDragExit: UIControlEvents = 1 << 5;
pub const UIControlEventTouchUpInside: UIControlEvents = 1 << 6;
const UIControlEventTouchUpOutside: UIControlEvents = 1 << 7;
pub const UIControlEventValueChanged: UIControlEvents = 1 << 12;

struct UIControlHostObject {
    superclass: super::UIViewHostObject,
    enabled: bool,
    selected: bool,
    highlighted: bool,
    /// `UITouch*` of the touch currently being tracked, [nil] if none
    tracked_touch: id,
    tracking: bool,
    /// See `addTarget:action:forControlEvents:`.
    ///
    /// UIKit documents targets as weak references, but touchHLE's emulated view
    /// and table-cell lifetimes are not exact enough yet. Retaining here avoids
    /// stale action targets when old games keep controls alive across cell
    /// reuse.
    action_targets: Vec<ActionTarget>,
}
#[derive(Copy, Clone)]
struct ActionTarget {
    target: id,
    action: SEL,
    events: UIControlEvents,
    host_retained: bool,
}
impl_HostObject_with_superclass!(UIControlHostObject);
impl Default for UIControlHostObject {
    fn default() -> Self {
        UIControlHostObject {
            superclass: Default::default(),
            enabled: true,
            selected: false,
            highlighted: false,
            tracked_touch: nil,
            tracking: false,
            action_targets: Vec::new(),
        }
    }
}

type UIControlState = NSUInteger;
pub const UIControlStateNormal: UIControlState = 0;
const UIControlStateHighlighted: UIControlState = 1 << 0;
const UIControlStateDisabled: UIControlState = 1 << 1;
const UIControlStateSelected: UIControlState = 1 << 2;
#[allow(dead_code)]
const UIControlStateFocused: UIControlState = 1 << 3;

fn send_actions(env: &mut Environment, this: id, event: id, control_event: UIControlEvents) {
    log_dbg!(
        "Control event {:?} in control {:?} for event {:?}",
        control_event,
        this,
        event,
    );

    let UIControlHostObject { action_targets, .. } = env.objc.borrow(this);
    let action_targets: Vec<_> = action_targets
        .iter()
        .filter(|action_target| (action_target.events & control_event) != 0)
        .map(|action_target| (action_target.target, action_target.action))
        .collect();

    for (target, action) in action_targets {
        assert!(target != nil); // TODO
        if env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2" {
            log!(
                "ZombieFarm2 UI action: control {:?} event {} -> {:?} {}",
                this,
                control_event,
                target,
                action.as_str(&env.mem),
            );
        }

        () = msg![env; this sendAction:action to:target forEvent:event];
    }
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

// abstract class
@implementation UIControl: UIView

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UIControlHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (())dealloc {
    let UIControlHostObject {
        superclass: _,
        enabled: _,
        selected: _,
        highlighted: _,
        tracking: _,
        action_targets,
        tracked_touch,
    } = std::mem::take(env.objc.borrow_mut(this));

    for action_target in action_targets {
        if action_target.host_retained {
            if env.objc.try_decrement_refcount(action_target.target) == Some(true) {
                let target = action_target.target;
                let _: () = msg![env; target dealloc];
            }
        } else {
            release(env, action_target.target);
        }
    }
    release(env, tracked_touch);

    msg_super![env; this dealloc]
}

- (UIControlState)state {
    let &UIControlHostObject {
        highlighted,
        enabled,
        selected,
        ..
    } = env.objc.borrow(this);
    // TODO: focussed
    let mut state = 0; // aka UIControlStateNormal
    if highlighted {
        state |= UIControlStateHighlighted;
    }
    if !enabled {
        state |= UIControlStateDisabled;
    }
    if selected {
        state |= UIControlStateSelected;
    }
    state
}

- (bool)isEnabled {
    env.objc.borrow::<UIControlHostObject>(this).enabled
}
- (())setEnabled:(bool)enabled {
    let bundle_id = env.bundle.bundle_identifier();
    if bundle_id.starts_with("com.playforge.ZombieFarm")
        || bundle_id.starts_with("com.playforge.ZFR")
    {
        log_dbg!(
            "ZombieFarm trace: UIControl {:?} setEnabled:{}",
            this,
            enabled,
        );
    }
    env.objc.borrow_mut::<UIControlHostObject>(this).enabled = enabled;
}

- (bool)isSelected {
    env.objc.borrow::<UIControlHostObject>(this).selected
}
- (())setSelected:(bool)selected {
    env.objc.borrow_mut::<UIControlHostObject>(this).selected = selected;
}

- (bool)isHighlighted {
    env.objc.borrow::<UIControlHostObject>(this).highlighted
}
- (())setHighlighted:(bool)highlighted {
    env.objc.borrow_mut::<UIControlHostObject>(this).highlighted = highlighted;
}

- (bool)tracking {
    env.objc.borrow::<UIControlHostObject>(this).tracking
}

- (bool)beginTrackingWithTouch:(id)_touch // UITouch*
                     withEvent:(id)_event { // UIEvent*
    // default implementation, subclasses can override this
    true
}
- (bool)continueTrackingWithTouch:(id)_touch // UITouch*
                        withEvent:(id)_event { // UIEvent*
    // default implementation, subclasses can override this
    true
}
- (())endTrackingWithTouch:(id)_touch // UITouch*
                  withEvent:(id)_event { // UIEvent*
    // default implementation, subclasses can override this, must call super
    // (for some reason, the docs say this default implementation updates the
    // tracking property? why here?)
    env.objc.borrow_mut::<UIControlHostObject>(this).tracking = false;
}

- (())touchesBegan:(id)touches // NSSet* of UITouch*
         withEvent:(id)event { // UIEvent*
    let bundle_id = env.bundle.bundle_identifier();
    let is_zombie_farm = bundle_id.starts_with("com.playforge.ZombieFarm")
        || bundle_id.starts_with("com.playforge.ZFR");
    let is_zombie_farm_start_button_ready = if is_zombie_farm
        && crate::frameworks::foundation::ns_notification_center::zombie_farm_startup_player_determined(env)
    {
        let play_tapped = env.objc.lookup_selector("playTapped").unwrap();
        env.objc
            .borrow::<UIControlHostObject>(this)
            .action_targets
            .iter()
            .any(|action_target| action_target.action == play_tapped)
    } else {
        false
    };
    if !msg![env; this isEnabled] && !is_zombie_farm_start_button_ready {
        if is_zombie_farm {
            log_dbg!(
                "ZombieFarm trace: UIControl {:?} ignored touchesBegan because it is disabled",
                this,
            );
        }
        return;
    }
    if is_zombie_farm_start_button_ready && !msg![env; this isEnabled] {
        log_dbg!(
            "ZombieFarm trace: allowing Play touch on disabled control {:?} after startup player determination",
            this,
        );
    }

    // UIControl's documentation implies that only one touch is ever tracked
    // at once.
    let touch: id = msg![env; touches anyObject];
    if !msg![env; this beginTrackingWithTouch:touch withEvent:event] {
        if is_zombie_farm {
            log_dbg!(
                "ZombieFarm trace: UIControl {:?} beginTrackingWithTouch returned false",
                this,
            );
        }
        return;
    }

    retain(env, touch);
    let host_obj = env.objc.borrow_mut::<UIControlHostObject>(this);
    host_obj.tracking = true;
    let old_touch = std::mem::replace(&mut host_obj.tracked_touch, touch);
    release(env, old_touch);
    if old_touch != nil {
        log!("Got new touch {:?} but old touch {:?} has not yet ended!", touch, old_touch);
    }
    // Not sure if this is the right place to set this.
    () = msg![env; this setHighlighted:true];

    // TODO: unclear if this is meant to be affected by tracking
    send_actions(env, this, event, UIControlEventTouchDown);
}
- (())touchesMoved:(id)touches // NSSet* of UITouch*
         withEvent:(id)event { // UIEvent*
    if !msg![env; this isEnabled] {
        return;
    }

    let touch: id = msg![env; touches anyObject];
    let tracked_touch = env.objc.borrow::<UIControlHostObject>(this).tracked_touch;
    if tracked_touch != touch {
        return;
    }
    if !msg![env; this continueTrackingWithTouch:touch withEvent:event] {
        release(env, tracked_touch);
        env.objc.borrow_mut::<UIControlHostObject>(this).tracked_touch = nil;
        env.objc.borrow_mut::<UIControlHostObject>(this).tracking = false;
        () = msg![env; this setHighlighted:false];
    }

    let old_pos: CGPoint = msg![env; touch previousLocationInView:this];
    let new_pos: CGPoint = msg![env; touch locationInView:this];
    let was_inside = msg![env; this pointInside:old_pos withEvent:event];
    let is_inside = msg![env; this pointInside:new_pos withEvent:event];

    // TODO: unclear if this is meant to be affected by tracking
    send_actions(env, this, event, match (was_inside, is_inside) {
        (true, true) => UIControlEventTouchDragInside,
        (false, false) => UIControlEventTouchDragOutside,
        (false, true) => UIControlEventTouchDragEnter,
        (true, false) => UIControlEventTouchDragExit,
    });
}
- (())touchesEnded:(id)touches // NSSet* of UITouch*
         withEvent:(id)event { // UIEvent*
    let touch: id = msg![env; touches anyObject];
    let tracked_touch = env.objc.borrow::<UIControlHostObject>(this).tracked_touch;
    if tracked_touch != touch {
        return;
    }
    () = msg![env; this endTrackingWithTouch:touch withEvent:event];
    release(env, tracked_touch);
    env.objc.borrow_mut::<UIControlHostObject>(this).tracked_touch = nil;
    () = msg![env; this setHighlighted:false];

    let new_pos: CGPoint = msg![env; touch locationInView:this];
    let is_inside = msg![env; this pointInside:new_pos withEvent:event];

    // TODO: unclear if this is meant to be affected by tracking
    send_actions(env, this, event, match is_inside {
        true => UIControlEventTouchUpInside,
        false => UIControlEventTouchUpOutside,
    });
}

- (())addTarget:(id)target
         action:(SEL)action
forControlEvents:(UIControlEvents)events {
    if target == nil {
        // TODO: when the target is nil, the responder chain is searched for
        // a suitable target
        log!(
            "TODO: [{:?} addTarget:nil action:{:?} forControlEvents:{:?}] (ignored)",
            target,
            action,
            events,
        );
        return;
    }
    let host_retained = env.objc.try_increment_refcount(target);
    if !host_retained {
        retain(env, target);
    }

    // The selector must be for a method with zero to two arguments
    let sel_str = action.as_str(&env.mem);
    let colon_count = sel_str.bytes().filter(|&b| b == b':').count();
    assert!([0, 1, 2].contains(&colon_count));
    let bundle_id = env.bundle.bundle_identifier();
    if bundle_id.starts_with("com.playforge.ZombieFarm")
        || bundle_id.starts_with("com.playforge.ZFR")
    {
        log_dbg!(
            "ZombieFarm trace: UIControl {:?} addTarget {:?} action {:?} events {:?}",
            this,
            target,
            sel_str,
            events,
        );
    }

    env.objc
        .borrow_mut::<UIControlHostObject>(this)
        .action_targets
        .push(ActionTarget {
            target,
            action,
            events,
            host_retained,
        });
}

- (())sendAction:(SEL)action
              to:(id)target
        forEvent:(id)event { // UIEvent*
    assert!(target != nil); // TODO

    let sel_str = action.as_str(&env.mem);
    let target_class = ObjC::read_isa(target, &env.mem);
    if target_class == nil {
        log!(
            "Warning: ignoring UIControl action {:?} to stale target {:?} with nil isa",
            sel_str,
            target,
        );
        return;
    }
    let colon_count = sel_str.bytes().filter(|&b| b == b':').count();
    match colon_count {
        // - (IBAction)action;
        0 => {
            log_dbg!(
                "Sending {:?} ({:?}) message to {:?} (no args)",
                action,
                sel_str,
                target
            );
            () = msg_send(env, (target, action));
        }
        // - (IBAction)action:(id)sender;
        1 => {
            log_dbg!(
                "Sending {:?} ({:?}) message to {:?} (one arg: {:?})",
                action,
                sel_str,
                target,
                this
            );
            () = msg_send(env, (target, action, this));
        }
        // - (IBAction)action:(id)sender forEvent:(UIEvent*)event;
        2 => {
            log_dbg!(
                "Sending {:?} ({:?}) message to {:?} (two args: {:?}, {:?})",
                action,
                sel_str,
                target,
                this,
                event
            );
            () = msg_send(env, (target, action, this, event));
        }
        _ => panic!(),
    };
}

// TODO: more triggers/targets/actions stuff

@end

};
