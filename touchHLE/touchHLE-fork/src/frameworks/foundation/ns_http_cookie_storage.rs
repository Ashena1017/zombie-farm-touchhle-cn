/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSHTTPCookieStorage`.

use crate::objc::{id, msg_class, nil, objc_classes, ClassExports, HostObject};

#[derive(Default)]
pub struct State {
    storage: Option<id>,
}

#[derive(Default)]
struct NSHTTPCookieStorageHostObject {
    accept_policy: u32,
}
impl HostObject for NSHTTPCookieStorageHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSHTTPCookieStorage: NSObject

+ (id)sharedHTTPCookieStorage {
    if let Some(storage) = env.framework_state.foundation.ns_http_cookie_storage.storage {
        storage
    } else {
        let storage = env.objc.alloc_static_object(
            this,
            Box::<NSHTTPCookieStorageHostObject>::default(),
            &mut env.mem
        );
        env.framework_state.foundation.ns_http_cookie_storage.storage = Some(storage);
        storage
    }
}

- (id)cookies {
    msg_class![env; NSArray array]
}

- (id)cookiesForURL:(id)_url {
    msg_class![env; NSArray array]
}

- (())setCookies:(id)_cookies forURL:(id)_url mainDocumentURL:(id)_main_document_url {
    log_dbg!("TODO: ignoring [(NSHTTPCookieStorage*){:?} setCookies:forURL:mainDocumentURL:]", this);
}

- (())setCookie:(id)_cookie {
    log_dbg!("TODO: ignoring [(NSHTTPCookieStorage*){:?} setCookie:]", this);
}

- (())deleteCookie:(id)_cookie {
    log_dbg!("TODO: ignoring [(NSHTTPCookieStorage*){:?} deleteCookie:]", this);
}

- (u32)cookieAcceptPolicy {
    env.objc.borrow::<NSHTTPCookieStorageHostObject>(this).accept_policy
}

- (())setCookieAcceptPolicy:(u32)policy {
    env.objc.borrow_mut::<NSHTTPCookieStorageHostObject>(this).accept_policy = policy;
}

@end

@implementation NSHTTPCookie: NSObject

+ (id)cookieWithProperties:(id)_properties {
    nil
}

- (id)initWithProperties:(id)_properties {
    nil
}

@end

};
