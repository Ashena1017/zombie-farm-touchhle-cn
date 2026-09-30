/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! MessageUI framework.

use crate::frameworks::foundation::NSInteger;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, nil, objc_classes, release, retain, ClassExports,
    NSZonePtr,
};
use crate::Environment;

const MFMailComposeResultSent: NSInteger = 2;

struct MFMailComposeViewControllerHostObject {
    superclass: crate::frameworks::uikit::ui_view_controller::UIViewControllerHostObject,
    delegate: id,
    finished: bool,
}
impl_HostObject_with_superclass!(MFMailComposeViewControllerHostObject);

impl Default for MFMailComposeViewControllerHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            delegate: nil,
            finished: false,
        }
    }
}

fn simulate_mail_compose_success(env: &mut Environment, controller: id) {
    let (delegate, should_finish) = {
        let host = env
            .objc
            .borrow::<MFMailComposeViewControllerHostObject>(controller);
        (host.delegate, !host.finished && host.delegate != nil)
    };
    if !should_finish {
        return;
    }

    let selector = "mailComposeController:didFinishWithResult:error:";
    if !env
        .objc
        .object_has_method_named(&env.mem, delegate, selector)
    {
        return;
    }

    env.objc
        .borrow_mut::<MFMailComposeViewControllerHostObject>(controller)
        .finished = true;
    let result = MFMailComposeResultSent;
    let _: () =
        msg![env; delegate mailComposeController:controller didFinishWithResult:result error:nil];
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation MFMailComposeViewController: UIViewController

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<MFMailComposeViewControllerHostObject>::default(), &mut env.mem)
}

+ (bool)canSendMail {
    log_dbg!("MFMailComposeViewController canSendMail -> true");
    true
}

- (())dealloc {
    let host = std::mem::take(env.objc.borrow_mut::<MFMailComposeViewControllerHostObject>(this));
    release(env, host.delegate);
    env.objc.dealloc_object(this, &mut env.mem);
}

- (())setMailComposeDelegate:(id)delegate {
    let old_delegate = {
        let host = env.objc.borrow_mut::<MFMailComposeViewControllerHostObject>(this);
        std::mem::replace(&mut host.delegate, delegate)
    };
    retain(env, delegate);
    release(env, old_delegate);
    simulate_mail_compose_success(env, this);
}

- (())setSubject:(id)_subject {
}

- (())setMessageBody:(id)_body isHTML:(bool)_is_html {
}

- (())setToRecipients:(id)_recipients {
}

- (())setCcRecipients:(id)_recipients {
}

- (())setBccRecipients:(id)_recipients {
}

- (())addAttachmentData:(id)_attachment mimeType:(id)_mime_type fileName:(id)_filename {
}

- (id)mailComposeDelegate {
    env.objc
        .borrow::<MFMailComposeViewControllerHostObject>(this)
        .delegate
}

- (())_touchHLE_simulateMailComposeSuccess {
    simulate_mail_compose_success(env, this);
}

@end

};

pub const DYLIB: crate::dyld::HostDylib = crate::dyld::HostDylib {
    path: "/System/Library/Frameworks/MessageUI.framework/MessageUI",
    aliases: &[],
    class_exports: &[CLASSES],
    constant_exports: &[],
    function_exports: &[],
};
