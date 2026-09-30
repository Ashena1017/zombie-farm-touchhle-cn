/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIActivityIndicatorView`.

use crate::frameworks::foundation::NSInteger;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, objc_classes, ClassExports, NSZonePtr,
};

type UIActivityIndicatorViewStyle = NSInteger;

pub struct UIActivityIndicatorViewHostObject {
    superclass: super::ui_view::UIViewHostObject,
    animating: bool,
}
impl_HostObject_with_superclass!(UIActivityIndicatorViewHostObject);

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIActivityIndicatorView: UIView

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(UIActivityIndicatorViewHostObject {
        superclass: Default::default(),
        animating: false,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (id)initWithActivityIndicatorStyle:(UIActivityIndicatorViewStyle)_style {
    let this: id = msg![env; this init];
    () = msg![env; this setUserInteractionEnabled:false];
    this
}

- (())setActivityIndicatorViewStyle:(UIActivityIndicatorViewStyle)style {
    log_dbg!("Ignoring setActivityIndicatorViewStyle:{} for {:?}", style, this);
}

- (())startAnimating {
    env.objc.borrow_mut::<UIActivityIndicatorViewHostObject>(this).animating = true;
}
- (())stopAnimating {
    env.objc.borrow_mut::<UIActivityIndicatorViewHostObject>(this).animating = false;
}

- (bool)isAnimating {
    env.objc.borrow::<UIActivityIndicatorViewHostObject>(this).animating
}

- (())setHidesWhenStopped:(bool)_hides {
    // TODO
}

@end

};
