/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UITouch`.

use super::ui_event;
use crate::frameworks::core_graphics::{CGPoint, CGRect};
use crate::frameworks::foundation::{NSInteger, NSTimeInterval, NSUInteger};
use crate::mem::MutVoidPtr;
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, Class, ClassExports,
    HostObject, NSZonePtr,
};
use crate::window::{Coords, Event, FingerId};
use crate::Environment;
use std::collections::hash_map::{Entry, HashMap};
use std::collections::HashSet;

pub type UITouchPhase = NSInteger;
pub const UITouchPhaseBegan: UITouchPhase = 0;
pub const UITouchPhaseMoved: UITouchPhase = 1;
pub const UITouchPhaseStationary: UITouchPhase = 2;
pub const UITouchPhaseEnded: UITouchPhase = 3;

const ZOMBIE_FARM_MOUSE_MOVE_DEAD_ZONE: f32 = 6.0;

#[derive(Default)]
pub struct State {
    current_touches: HashMap<FingerId, id>,
}

pub(super) struct UITouchHostObject {
    /// Strong reference to the `UIView`
    pub(super) view: id,
    /// Strong reference to the `UIWindow`, used as a reference for co-ordinate
    /// space conversion
    pub(super) window: id,
    /// Relative to the screen
    location: CGPoint,
    /// Relative to the screen
    previous_location: CGPoint,
    timestamp: NSTimeInterval,
    phase: UITouchPhase,
}
impl HostObject for UITouchHostObject {}

fn is_zombie_farm_2(env: &Environment) -> bool {
    env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2"
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UITouch: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(UITouchHostObject {
        view: nil,
        window: nil,
        location: CGPoint { x: 0.0, y: 0.0 },
        previous_location: CGPoint { x: 0.0, y: 0.0 },
        timestamp: 0.0,
        phase: UITouchPhaseBegan,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (())dealloc {
    let &mut UITouchHostObject { view, window, .. } = env.objc.borrow_mut(this);
    release(env, view);
    release(env, window);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (CGPoint)locationInView:(id)that_view { // UIView*
    let &UITouchHostObject { location, window, .. } = env.objc.borrow(this);
    let location_in_window: CGPoint = msg![env; window convertPoint:location fromWindow:nil];
    if that_view == nil {
        location_in_window
    } else {
        msg![env; that_view convertPoint:location_in_window fromView:window]
    }
}
- (CGPoint)previousLocationInView:(id)that_view { // UIView*
    let &UITouchHostObject { previous_location, window, .. } = env.objc.borrow(this);
    let location_in_window: CGPoint = msg![env; window convertPoint:previous_location fromWindow:nil];
    if that_view == nil {
        location_in_window
    } else {
        msg![env; that_view convertPoint:location_in_window fromView:window]
    }
}

- (id)view {
    env.objc.borrow::<UITouchHostObject>(this).view
}

- (NSTimeInterval)timestamp {
    env.objc.borrow::<UITouchHostObject>(this).timestamp
}

- (NSUInteger)tapCount {
    1 // TODO: support double-taps etc
}

- (UITouchPhase)phase {
    env.objc.borrow::<UITouchHostObject>(this).phase
}

@end

};

/// [super::handle_events] will forward touch events to this function.
pub fn handle_event(env: &mut Environment, event: Event) {
    // before processing anything, we mark all current touches as stationary
    let current_touches = &env.framework_state.uikit.ui_touch.current_touches;
    for &touch in (*current_touches).values() {
        env.objc.borrow_mut::<UITouchHostObject>(touch).phase = UITouchPhaseStationary;
    }
    match event {
        Event::TouchesDown(map) => handle_touches_down(env, map),
        Event::TouchesMove(map) => handle_touches_move(env, map),
        Event::TouchesUp(map) => handle_touches_up(env, map),
        _ => unreachable!(),
    }
}

fn handle_touches_down(env: &mut Environment, map: HashMap<FingerId, Coords>) {
    // UIKit creates and drains autorelease pools when handling events.
    let pool: id = msg_class![env; NSAutoreleasePool new];

    // Note: if the emulator is heavily lagging, this timestamp is going
    // to be far off from the truth, since it should represent the
    // time when the event actually happened, not the time when the
    // event was dispatched. Maybe we'll need to fix this eventually.
    let timestamp: NSTimeInterval = {
        let process_info = msg_class![env; NSProcessInfo processInfo];
        msg![env; process_info systemUptime]
    };

    let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];

    for (finger_id, coords) in map {
        let current_touches = &mut env.framework_state.uikit.ui_touch.current_touches;

        if current_touches.contains_key(&finger_id) {
            // this seems to happen only on the desktop with a single touch
            assert_eq!(current_touches.len(), 1);
            log!(
                "Warning: New touch {:?} initiated but current touch did not end yet, treating as movement.",
                finger_id
            );
            return handle_touches_move(env, HashMap::from([(finger_id, coords)]));
        }

        log_dbg!("Finger {:?} touch down: {:?}", finger_id, coords);

        let location = CGPoint {
            x: coords.0,
            y: coords.1,
        };

        // TODO: is this the correct state of the UITouch and UIEvent during
        //       hit testing?

        let new_touch: id = msg_class![env; UITouch alloc];
        *env.objc.borrow_mut(new_touch) = UITouchHostObject {
            view: nil,
            window: nil,
            location,
            previous_location: location,
            timestamp,
            phase: UITouchPhaseBegan,
        };
        autorelease(env, new_touch);

        let _: () = msg![env; touches addObject:new_touch];

        let _ = &env
            .framework_state
            .uikit
            .ui_touch
            .current_touches
            .insert(finger_id, new_touch);
        retain(env, new_touch);
    }

    let all_touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
    for &touch in env
        .framework_state
        .uikit
        .ui_touch
        .current_touches
        .clone()
        .values()
    {
        let _: () = msg![env; all_touches addObject:touch];
    }

    let event = ui_event::new_event(env, all_touches);
    autorelease(env, event);

    // views with existing touches (see isMultipleTouchEnabled check below)
    let views_with_existing_touches: HashSet<id> = env
        .framework_state
        .uikit
        .ui_touch
        .current_touches
        .values()
        .map(|&touch| env.objc.borrow::<UITouchHostObject>(touch).view)
        .collect();

    // view to set of touches for this view
    let mut view_touches: HashMap<id, id> = HashMap::new();

    let touches_arr: id = msg![env; touches allObjects];
    let touches_count: NSUInteger = msg![env; touches_arr count];
    for i in 0..touches_count {
        let touch: id = msg![env; touches_arr objectAtIndex:i];
        let &UITouchHostObject { location, .. } = env.objc.borrow(touch);

        // Assumes the windows in the list are ordered back-to-front.
        // TODO: this may not be correct once we support windowLevel.
        //
        // If a higher window only contributes a transparent/non-interactive
        // placeholder view, its UIView hit-test result is the window itself.
        // Keep looking through lower windows so EAGL-backed games can still
        // receive touches.
        let windows = env.framework_state.uikit.ui_view.ui_window.windows.clone();
        let mut fallback_window_hit = None;
        let mut selected_window_hit = None;
        for window in windows.into_iter().rev() {
            let location_in_window: CGPoint =
                msg![env; window convertPoint:location fromWindow:nil];
            if !msg![env; window pointInside:location_in_window withEvent:event] {
                continue;
            }
            let view: id = msg![env; window hitTest:location_in_window withEvent:event];
            if view == nil {
                continue;
            }
            if view == window {
                fallback_window_hit.get_or_insert((window, location_in_window, view));
                continue;
            }
            selected_window_hit = Some((window, location_in_window, view));
            break;
        }
        let Some((window, location_in_window, view)) = selected_window_hit.or(fallback_window_hit)
        else {
            log!(
                "Couldn't find a window for touch at {:?}, discarding",
                location,
            );
            continue;
        };

        let view_class: Class = msg![env; view class];
        let view_class_name = env.objc.get_class_name(view_class).to_string();
        let view_frame: CGRect = msg![env; view frame];
        log_dbg!(
            "Found view {:?} ({}) with frame {:?} for touch at {:?} in window {:?}",
            view,
            view_class_name,
            view_frame,
            location_in_window,
            window,
        );
        if is_zombie_farm_2(env) {
            log!(
                "ZombieFarm2 UI hit trace: touch down selected view {:?} ({}) frame {:?} at {:?}",
                view,
                view_class_name,
                view_frame,
                location_in_window,
            );
        }

        let is_multi_touch_enabled: bool = msg![env; view isMultipleTouchEnabled];
        if !is_multi_touch_enabled {
            // When a view has multi-touch disabled, it can only have one active
            // touch at once. So, we can only report a new touch to the view if
            // there are no other touches currently associated with it, and if
            // there are multiple new touches for this view, we can only report
            // one of them.
            let view_has_other_new_touches = view_touches.contains_key(&view);
            let view_has_existing_touches = views_with_existing_touches.contains(&view);
            if view_has_other_new_touches || view_has_existing_touches {
                log!(
                    "Ignoring new touch {:?} for view {:?}, !isMultipleTouchEnabled",
                    touch,
                    view
                );
                // The touch will continue to be tracked until it ends, but the
                // view will be nil, so messages sent to it will be ignored.
                // TODO: Figure out if/how these should be delivered elsewhere
                //       in the responder chain.
                // FIXME: The fact the view is nil might be observed via
                //        touchesForView:nil or allTouches on UIEvent.
                //        This might cause problems. What does the real OS do?
                //        Does this need to be prevented?
                continue;
            }
        }

        // Only create the set after the isMultipleTouchEnabled checks so we
        // won't end up with an empty set.
        if let Entry::Vacant(e) = view_touches.entry(view) {
            let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
            e.insert(touches);
        }
        let touches: id = *view_touches.get(&view).unwrap();
        let _: () = msg![env; touches addObject:touch];

        retain(env, view);
        retain(env, window);
        {
            let new_touch = env.objc.borrow_mut::<UITouchHostObject>(touch);
            new_touch.view = view;
            new_touch.window = window;
        }
    }

    for (view, touches) in view_touches {
        log_dbg!(
            "Sending [{:?} touchesBegan:{:?} withEvent:{:?}]",
            view,
            touches,
            event
        );
        let _: () = msg![env; view touchesBegan:touches withEvent:event];
    }

    release(env, pool);
}

fn handle_touches_move(env: &mut Environment, map: HashMap<FingerId, Coords>) {
    let scroll_profile = crate::zombie_farm_debug::scroll_profile_enabled_for_bundle(env);
    let scroll_profile_start = scroll_profile.then(std::time::Instant::now);
    if scroll_profile {
        crate::zombie_farm_debug::record_scroll_profile_count(
            crate::zombie_farm_debug::ScrollProfileBucket::UiTouchMoveInput,
            std::time::Duration::from_nanos(0),
            map.len() as u64,
        );
    }

    let pool: id = msg_class![env; NSAutoreleasePool new];

    let timestamp: NSTimeInterval = {
        let process_info = msg_class![env; NSProcessInfo processInfo];
        msg![env; process_info systemUptime]
    };

    let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];

    // view to set of touches for this view
    let mut view_touches: HashMap<id, id> = HashMap::new();
    let mut moved_touch_count = 0u64;

    for (finger_id, coords) in map {
        let Some(&touch) = env
            .framework_state
            .uikit
            .ui_touch
            .current_touches
            .get(&finger_id)
        else {
            log!(
                "Warning: Finger {:?} touch move event received but no current touch, ignoring.",
                finger_id
            );
            continue;
        };

        let location = CGPoint {
            x: coords.0,
            y: coords.1,
        };

        let use_move_dead_zone = is_zombie_farm_2(env) && matches!(finger_id, FingerId::Mouse);
        let view = env.objc.borrow::<UITouchHostObject>(touch).view;
        let host_object = env.objc.borrow_mut::<UITouchHostObject>(touch);

        if host_object.location == location {
            continue;
        }

        if use_move_dead_zone {
            let dx = location.x - host_object.location.x;
            let dy = location.y - host_object.location.y;
            if dx * dx + dy * dy
                < ZOMBIE_FARM_MOUSE_MOVE_DEAD_ZONE * ZOMBIE_FARM_MOUSE_MOVE_DEAD_ZONE
            {
                continue;
            }
        }

        host_object.previous_location = host_object.location;
        host_object.location = location;
        host_object.timestamp = timestamp;
        assert_eq!(host_object.phase, UITouchPhaseStationary);
        host_object.phase = UITouchPhaseMoved;

        let _: () = msg![env; touches addObject:touch];
        moved_touch_count += 1;

        if let Entry::Vacant(e) = view_touches.entry(view) {
            let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
            e.insert(touches);
        }
        let touches: id = *view_touches.get(&view).unwrap();
        let _: () = msg![env; touches addObject:touch];
    }

    let all_touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
    for &touch in env
        .framework_state
        .uikit
        .ui_touch
        .current_touches
        .clone()
        .values()
    {
        let _: () = msg![env; all_touches addObject:touch];
    }

    let event = ui_event::new_event(env, all_touches);
    autorelease(env, event);

    for (view, touches) in view_touches {
        let _: () = msg![env; view touchesMoved:touches withEvent:event];
    }

    if let Some(start) = scroll_profile_start {
        crate::zombie_farm_debug::record_scroll_profile_count(
            crate::zombie_farm_debug::ScrollProfileBucket::UiTouchMoveDispatch,
            start.elapsed(),
            moved_touch_count,
        );
    }

    release(env, pool);
}

fn handle_touches_up(env: &mut Environment, map: HashMap<FingerId, Coords>) {
    let pool: id = msg_class![env; NSAutoreleasePool new];

    let timestamp: NSTimeInterval = {
        let process_info = msg_class![env; NSProcessInfo processInfo];
        msg![env; process_info systemUptime]
    };

    let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];

    // We need to construct all touches set _BEFORE_ removing touches!
    // (as removed one are reported as the part of the event)
    let all_touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
    for &touch in env
        .framework_state
        .uikit
        .ui_touch
        .current_touches
        .clone()
        .values()
    {
        let _: () = msg![env; all_touches addObject:touch];
    }

    // view to set of touches for this view
    let mut view_touches: HashMap<id, id> = HashMap::new();

    for (finger_id, coords) in map {
        let Some(&touch) = env
            .framework_state
            .uikit
            .ui_touch
            .current_touches
            .get(&finger_id)
        else {
            log!(
                "Warning: Finger {:?} touch up event received but no current touch, ignoring.",
                finger_id
            );
            continue;
        };

        log_dbg!("Finger {:?} touch up: {:?}", finger_id, coords);

        let location = CGPoint {
            x: coords.0,
            y: coords.1,
        };

        let view = env.objc.borrow::<UITouchHostObject>(touch).view;
        let host_object = env.objc.borrow_mut::<UITouchHostObject>(touch);
        host_object.previous_location = host_object.location;
        host_object.location = location;
        host_object.timestamp = timestamp;
        assert_eq!(host_object.phase, UITouchPhaseStationary);
        host_object.phase = UITouchPhaseEnded;

        let _: () = msg![env; touches addObject:touch];

        if let Entry::Vacant(e) = view_touches.entry(view) {
            let touches: id = msg_class![env; NSMutableSet allocWithZone:(MutVoidPtr::null())];
            e.insert(touches);
        }
        let touches: id = *view_touches.get(&view).unwrap();
        let _: () = msg![env; touches addObject:touch];

        let _ = &env
            .framework_state
            .uikit
            .ui_touch
            .current_touches
            .remove(&finger_id);
        release(env, touch); // only owner now should be the NSSet
    }

    let event = ui_event::new_event(env, all_touches);
    autorelease(env, event);

    for (view, touches) in view_touches {
        log_dbg!(
            "Sending [{:?} touchesEnded:{:?} withEvent:{:?}]",
            view,
            touches,
            event
        );
        let _: () = msg![env; view touchesEnded:touches withEvent:event];
    }

    release(env, pool);
}
