/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSUUID`.

use super::ns_string::from_rust_string;
use crate::objc::{autorelease, id, msg, nil, objc_classes, ClassExports, HostObject, NSZonePtr};

const DEFAULT_UUID: &str = "00000000-0000-0000-0000-000000000000";

#[derive(Default)]
struct NSUUIDHostObject {
    uuid: String,
}
impl HostObject for NSUUIDHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSUUID: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSUUIDHostObject>::default(), &mut env.mem)
}

+ (id)UUID {
    let uuid: id = msg![env; this alloc];
    let uuid: id = msg![env; uuid init];
    autorelease(env, uuid)
}

- (id)init {
    env.objc.borrow_mut::<NSUUIDHostObject>(this).uuid = DEFAULT_UUID.to_string();
    this
}

- (id)initWithUUIDString:(id)string {
    let uuid = if string == nil {
        DEFAULT_UUID.to_string()
    } else {
        super::ns_string::to_rust_string(env, string).into_owned()
    };
    env.objc.borrow_mut::<NSUUIDHostObject>(this).uuid = uuid;
    this
}

- (id)UUIDString {
    let uuid = env.objc.borrow::<NSUUIDHostObject>(this).uuid.clone();
    let string = from_rust_string(env, uuid);
    autorelease(env, string)
}

@end

};
