/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSTimeZone`.

use crate::frameworks::foundation::{ns_string, NSInteger};
use crate::libc::time::current_local_timezone_offset_seconds;
use crate::objc::{autorelease, id, nil, release, retain, ClassExports, HostObject, NSZonePtr};
use crate::{msg, objc_classes};

struct NSTimeZoneHostObject {
    // NSString*
    time_zone: id,
    seconds_from_gmt: NSInteger,
}
impl HostObject for NSTimeZoneHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSTimeZone: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSTimeZoneHostObject {
        time_zone: nil,
        seconds_from_gmt: 0,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)timeZoneWithName:(id)tz_name {
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithName:tz_name];
    autorelease(env, new)
}

+ (id)localTimeZone {
    let tz_name: id = ns_string::get_static_str(env, "Local");
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithName:tz_name];
    env.objc.borrow_mut::<NSTimeZoneHostObject>(new).seconds_from_gmt =
        current_local_timezone_offset_seconds();
    autorelease(env, new)
}

+ (id)systemTimeZone {
    msg![env; this localTimeZone]
}

+ (id)defaultTimeZone {
    msg![env; this localTimeZone]
}

+ (id)timeZoneForSecondsFromGMT:(NSInteger)seconds {
    let tz_name: id = ns_string::from_rust_string(env, format!("GMT{seconds:+}"));
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithName:tz_name];
    release(env, tz_name);
    env.objc.borrow_mut::<NSTimeZoneHostObject>(new).seconds_from_gmt = seconds;
    autorelease(env, new)
}

+ (id)timeZoneWithAbbreviation:(id)abbreviation {
    msg![env; this timeZoneWithName:abbreviation]
}

- (())dealloc {
    let tz_name = env.objc.borrow_mut::<NSTimeZoneHostObject>(this).time_zone;
    release(env, tz_name);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)initWithName:(id)tz_name { // NSString *
    assert_ne!(tz_name, nil);
    let name = ns_string::to_rust_string(env, tz_name);
    let seconds_from_gmt = match name.as_ref() {
        "UTC" | "GMT" | "Etc/UTC" | "Etc/GMT" => 0,
        "Asia/Shanghai" | "Asia/Chongqing" | "Asia/Harbin" | "Asia/Urumqi" | "CST" => 8 * 3600,
        "Local" => current_local_timezone_offset_seconds(),
        _ => current_local_timezone_offset_seconds(),
    };
    retain(env, tz_name);
    let host_obj = env.objc.borrow_mut::<NSTimeZoneHostObject>(this);
    host_obj.time_zone = tz_name;
    host_obj.seconds_from_gmt = seconds_from_gmt;
    this
}

- (id)name {
    env.objc.borrow_mut::<NSTimeZoneHostObject>(this).time_zone
}

- (NSInteger)secondsFromGMT {
    env.objc.borrow::<NSTimeZoneHostObject>(this).seconds_from_gmt
}

@end

};
