/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

//! `NSAssertionHandler`.

use super::ns_string::{self, to_rust_string};
use super::NSInteger;
use crate::objc::{
    autorelease, id, msg, nil, objc_classes, ClassExports, HostObject, NSZonePtr, SEL,
};
use crate::Environment;

struct NSAssertionHandlerHostObject {}
impl HostObject for NSAssertionHandlerHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSAssertionHandler: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::new(NSAssertionHandlerHostObject {}), &mut env.mem)
}

+ (id)currentHandler {
    let handler: id = msg![env; this new];
    autorelease(env, handler)
}

- (())handleFailureInMethod:(SEL)selector
                     object:(id)object
                       file:(id)file_name
                 lineNumber:(NSInteger)line
                description:(id)format, ...args {
    let message = assertion_message(env, format, args.start());
    let file = if file_name == nil {
        "(null)".into()
    } else {
        to_rust_string(env, file_name).into_owned()
    };
    let object_desc = if object == nil {
        "(null)".into()
    } else {
        let desc: id = msg![env; object description];
        if desc == nil {
            format!("{object:?}")
        } else {
            to_rust_string(env, desc).into_owned()
        }
    };
    log!(
        "Warning: NSAssertionHandler ignored method assertion {} on {} at {}:{}: {}",
        selector.as_str(&env.mem),
        object_desc,
        file,
        line,
        message
    );
}

- (())handleFailureInFunction:(id)function_name
                         file:(id)file_name
                   lineNumber:(NSInteger)line
                  description:(id)format, ...args {
    let message = assertion_message(env, format, args.start());
    let function = if function_name == nil {
        "(null)".into()
    } else {
        to_rust_string(env, function_name).into_owned()
    };
    let file = if file_name == nil {
        "(null)".into()
    } else {
        to_rust_string(env, file_name).into_owned()
    };
    log!(
        "Warning: NSAssertionHandler ignored function assertion {} at {}:{}: {}",
        function,
        file,
        line,
        message
    );
}

@end

};

fn assertion_message(env: &mut Environment, format: id, args: crate::abi::VaList) -> String {
    if format == nil {
        return String::new();
    }

    ns_string::with_format(env, format, args)
}
