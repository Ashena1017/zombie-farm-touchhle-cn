/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIAlertView`.

use crate::frameworks::foundation::ns_string;
use crate::frameworks::foundation::NSInteger;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_super, nil, objc_classes, ClassExports, NSZonePtr,
};
use crate::Environment;
use std::borrow::Cow;

struct UIAlertViewHostObject {
    superclass: super::UIViewHostObject,
    delegate: id,
    button_count: NSInteger,
}
impl_HostObject_with_superclass!(UIAlertViewHostObject);

impl Default for UIAlertViewHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            delegate: nil,
            button_count: 0,
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

- (id)initWithTitle:(id)title
                      message:(id)message
                     delegate:(id)delegate
            cancelButtonTitle:(id)cancelButtonTitle
            otherButtonTitles:(id)otherButtonTitles {

    let msg = if message == nil { Cow::from("(nil)") } else { ns_string::to_rust_string(env, message) };
    let title = if title == nil { Cow::from("(nil)") } else { ns_string::to_rust_string(env, title) };
    log!("UIAlertView: title: {:?}, message: {:?}", title, msg);

    let this: id = msg_super![env; this init];
    if this != nil {
        let host = env.objc.borrow_mut::<UIAlertViewHostObject>(this);
        host.delegate = delegate;
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
    env.objc.borrow_mut::<UIAlertViewHostObject>(this).button_count += 1;
}

- (())show {
    log_dbg!("[(UIAlertView*){:?} show]", this);
    let (delegate, button_count) = {
        let host = env.objc.borrow::<UIAlertViewHostObject>(this);
        (host.delegate, host.button_count)
    };
    let button_index = if button_count > 0 { 0 } else { -1 };
    auto_dismiss_alert(env, this, delegate, button_index);
}

@end

};
