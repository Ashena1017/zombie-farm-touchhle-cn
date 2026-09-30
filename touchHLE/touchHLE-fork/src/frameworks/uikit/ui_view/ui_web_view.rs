/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UIWebView`.

use crate::frameworks::foundation::ns_string::{get_static_str, to_rust_string};
use crate::msg;
use crate::objc::{id, nil, objc_classes, ClassExports};
use std::borrow::Cow;

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIWebView: UIView

// NSCoding implementation
- (id)initWithCoder:(id)_coder {
    todo!()
}

- (())setScalesPageToFit:(bool)_scales {
    // TODO
}
- (())setDelegate:(id)_delegate {
    // TODO
}
- (id)delegate {
    nil
}
- (())loadRequest:(id)request { // NSURLRequest*
    let url_string = if request != nil {
        let url = msg![env; request URL];
        let url_desc = msg![env; url description];
        to_rust_string(env, url_desc)
    } else {
        Cow::default()
    };
    log!("TODO: [(UIWebView*) {:?} loadRequest:{:?} ({})]", this, request, url_string);
}

- (())loadHTMLString:(id)string // NSString*
              baseURL:(id)base_url { // NSURL*
    let html_len = if string != nil {
        to_rust_string(env, string).len()
    } else {
        0
    };
    let base_url_desc = if base_url != nil {
        let desc = msg![env; base_url description];
        to_rust_string(env, desc)
    } else {
        Cow::default()
    };
    log_dbg!(
        "[(UIWebView*) {:?} loadHTMLString:<{} bytes> baseURL:{:?} ({})]",
        this,
        html_len,
        base_url,
        base_url_desc
    );
}

- (id)stringByEvaluatingJavaScriptFromString:(id)script {
    let script_len = if script != nil {
        to_rust_string(env, script).len()
    } else {
        0
    };
    log_dbg!(
        "[(UIWebView*) {:?} stringByEvaluatingJavaScriptFromString:<{} bytes>] -> empty string",
        this,
        script_len
    );
    get_static_str(env, "")
}

@end

};
