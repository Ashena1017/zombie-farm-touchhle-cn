/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIAlertView`.

use crate::frameworks::foundation::ns_string;
use crate::frameworks::foundation::NSInteger;
use crate::objc::{
    autorelease, id, impl_HostObject_with_superclass, msg, msg_super, nil, objc_classes, retain,
    ClassExports, NSZonePtr,
};
use crate::Environment;
use std::borrow::Cow;

#[derive(Clone)]
struct SingleButtonText {
    title: Cow<'static, str>,
    message: Cow<'static, str>,
    button_title: Cow<'static, str>,
}

struct UIAlertViewHostObject {
    superclass: super::UIViewHostObject,
    delegate: id,
    button_count: NSInteger,
    single_button_text: Option<SingleButtonText>,
    showing_about: bool,
}
impl_HostObject_with_superclass!(UIAlertViewHostObject);

impl Default for UIAlertViewHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            delegate: nil,
            button_count: 0,
            single_button_text: None,
            showing_about: false,
        }
    }
}

fn alert_delegate_responds(env: &Environment, delegate: id, selector: &str) -> bool {
    delegate != nil
        && env
            .objc
            .object_has_method_named(&env.mem, delegate, selector)
}

fn auto_dismiss_alert(env: &mut Environment, alert: id, delegate: id, button_index: NSInteger) {
    if alert_delegate_responds(env, delegate, "alertView:willDismissWithButtonIndex:") {
        let _: () = msg![env; delegate alertView:alert willDismissWithButtonIndex:button_index];
    }
    if alert_delegate_responds(env, delegate, "alertView:clickedButtonAtIndex:") {
        let _: () = msg![env; delegate alertView:alert clickedButtonAtIndex:button_index];
    }
    if alert_delegate_responds(env, delegate, "alertView:didDismissWithButtonIndex:") {
        let _: () = msg![env; delegate alertView:alert didDismissWithButtonIndex:button_index];
    }
    if button_index < 0 && alert_delegate_responds(env, delegate, "alertViewCancel:") {
        let _: () = msg![env; delegate alertViewCancel:alert];
    }
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIAlertView: UIView

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<UIAlertViewHostObject>::default(), &mut env.mem)
}

+ (())_touchHLE_confirmAbout:(id)sender {
    let alert: id = msg![env; sender superview];
    if alert == nil || !msg![env; alert isKindOfClass:this] {
        return;
    }
    let host = env.objc.borrow_mut::<UIAlertViewHostObject>(alert);
    if !std::mem::take(&mut host.showing_about) {
        return;
    }
    let delegate = host.delegate;
    let mask: id = msg![env; alert superview];
    // Removing the mask drops its owning reference. Keep the alert and its
    // control alive until UIKit has finished dispatching the current touch.
    retain(env, mask);
    autorelease(env, mask);
    () = msg![env; mask removeFromSuperview];
    auto_dismiss_alert(env, alert, delegate, 0);
}

- (id)initWithTitle:(id)title
                      message:(id)message
                     delegate:(id)delegate
            cancelButtonTitle:(id)cancelButtonTitle
            otherButtonTitles:(id)otherButtonTitles {

    let single_button = delegate == nil && title != nil && message != nil
        && cancelButtonTitle != nil && otherButtonTitles == nil;
    let message = if message == nil { Cow::from("(nil)") } else { ns_string::to_rust_string(env, message) };
    let title = if title == nil { Cow::from("(nil)") } else { ns_string::to_rust_string(env, title) };
    log!("UIAlertView: title: {:?}, message: {:?}", title, message);
    let single_button_text = single_button.then(|| SingleButtonText {
        title,
        message,
        button_title: ns_string::to_rust_string(env, cancelButtonTitle),
    });

    let this: id = msg_super![env; this init];
    if this != nil {
        let host = env.objc.borrow_mut::<UIAlertViewHostObject>(this);
        host.delegate = delegate;
        host.single_button_text = single_button_text;
        host.button_count = 0;
        if cancelButtonTitle != nil {
            host.button_count += 1;
        }
        if otherButtonTitles != nil {
            host.button_count += 1;
        }
    }
    this
}

- (())addButtonWithTitle:(id)title {
    log_dbg!("[(UIAlertView *){:?} addButtonWithTitle:{}]", this, ns_string::to_rust_string(env, title));
    let host = env.objc.borrow_mut::<UIAlertViewHostObject>(this);
    host.button_count += 1;
    host.single_button_text = None;
}

- (())show {
    log_dbg!("[(UIAlertView*){:?} show]", this);
    let host = env.objc.borrow::<UIAlertViewHostObject>(this);
    if host.showing_about {
        return;
    }
    let (delegate, button_count) = (host.delegate, host.button_count);
    if let Some(text) = host.single_button_text.clone() {
        if crate::objc::zfr_about_alert::present(env, this, &text.title, &text.message, &text.button_title) {
            env.objc.borrow_mut::<UIAlertViewHostObject>(this).showing_about = true;
            return;
        }
    }
    let button_index = if button_count > 0 { 0 } else { -1 };
    auto_dismiss_alert(env, this, delegate, button_index);
}

@end

};
