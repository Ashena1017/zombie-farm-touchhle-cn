/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! The AdSupport framework.

use crate::dyld::HostDylib;
use crate::objc::{
    autorelease, id, msg, msg_class, objc_classes, ClassExports, HostObject, NSZonePtr,
};

pub const DYLIB: HostDylib = HostDylib {
    path: "/System/Library/Frameworks/AdSupport.framework/AdSupport",
    aliases: &[],
    class_exports: &[CLASSES],
    constant_exports: &[],
    function_exports: &[],
};

#[derive(Default)]
struct ASIdentifierManagerHostObject {}
impl HostObject for ASIdentifierManagerHostObject {}

const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation ASIdentifierManager: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<ASIdentifierManagerHostObject>::default(), &mut env.mem)
}

+ (id)sharedManager {
    let manager: id = msg![env; this alloc];
    let manager: id = msg![env; manager init];
    autorelease(env, manager)
}

- (id)advertisingIdentifier {
    msg_class![env; NSUUID UUID]
}

- (bool)isAdvertisingTrackingEnabled {
    false
}

@end

};
