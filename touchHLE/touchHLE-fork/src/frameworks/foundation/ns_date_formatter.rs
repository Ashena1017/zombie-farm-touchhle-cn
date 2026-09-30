/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSDateFormatter`.
//!
//! Resources:
//! - Apple's [Introduction to Data Formatting Programming Guide For Cocoa](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/DataFormatting/DataFormatting.html)
//! - [Unicode Technical Standard #35](https://unicode.org/reports/tr35/tr35-10.html#Date_Format_Patterns)

use crate::frameworks::foundation::{ns_string, NSTimeInterval, NSUInteger};
use crate::libc::time::current_local_timezone_offset_seconds;
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject,
    NSZonePtr,
};
use chrono::{FixedOffset, NaiveDateTime, TimeZone};

struct NSDateFormatterHostObject {
    date_format: Option<id>,
    time_zone: id,
    formatter_behavior: NSUInteger,
}
impl HostObject for NSDateFormatterHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSDateFormatter: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSDateFormatterHostObject {
        date_format: None,
        time_zone: nil,
        formatter_behavior: 0,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (())dealloc {
    let (date_format, time_zone) = {
        let host_obj = env.objc.borrow_mut::<NSDateFormatterHostObject>(this);
        (host_obj.date_format.take(), host_obj.time_zone)
    };
    if let Some(date_format) = date_format {
        release(env, date_format);
    }
    release(env, time_zone);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (())setDateFormat:(id)format { // NSString *
    let date_format: id = msg![env; format copy];
    let host_obj = env.objc.borrow_mut::<NSDateFormatterHostObject>(this);
    if let Some(old) = host_obj.date_format.replace(date_format) {
        release(env, old);
    }
}

- (NSUInteger)formatterBehavior {
    env.objc.borrow::<NSDateFormatterHostObject>(this).formatter_behavior
}

- (())setFormatterBehavior:(NSUInteger)behavior {
    env.objc.borrow_mut::<NSDateFormatterHostObject>(this).formatter_behavior = behavior;
}

- (id)timeZone {
    let time_zone = env.objc.borrow::<NSDateFormatterHostObject>(this).time_zone;
    if time_zone != nil {
        time_zone
    } else {
        msg_class![env; NSTimeZone localTimeZone]
    }
}

- (())setTimeZone:(id)time_zone {
    retain(env, time_zone);
    let old = std::mem::replace(&mut env.objc.borrow_mut::<NSDateFormatterHostObject>(this).time_zone, time_zone);
    release(env, old);
}

- (id)stringFromDate:(id)date {
    let Some(format) = formatter_format(env, this) else {
        return nil;
    };
    let Some(chrono_format) = translate_date_format(&format) else {
        log!("Warning: NSDateFormatter unsupported date format {:?}", format);
        return nil;
    };
    let ti: NSTimeInterval = msg![env; date timeIntervalSince1970];
    let offset = formatter_offset_seconds(env, this);
    let Some(offset) = FixedOffset::east_opt(offset) else {
        return nil;
    };
    let secs = ti.floor() as i64;
    let nanos = ((ti - secs as f64) * 1_000_000_000.0).round().max(0.0) as u32;
    let Some(date_time) = offset.timestamp_opt(secs, nanos).single() else {
        return nil;
    };
    let res = ns_string::from_rust_string(env, date_time.format(&chrono_format).to_string());
    autorelease(env, res)
}

- (id)dateFromString:(id)string {
    let Some(format) = formatter_format(env, this) else {
        return nil;
    };
    let Some(chrono_format) = translate_date_format(&format) else {
        log!("Warning: NSDateFormatter unsupported date format {:?}", format);
        return nil;
    };
    let string = ns_string::to_rust_string(env, string);
    let timestamp = if chrono_format.contains("%z") {
        match chrono::DateTime::parse_from_str(&string, &chrono_format) {
            Ok(date) => date.timestamp() as f64 + f64::from(date.timestamp_subsec_nanos()) / 1_000_000_000.0,
            Err(_) => return nil,
        }
    } else {
        let Ok(date) = NaiveDateTime::parse_from_str(&string, &chrono_format) else {
            return nil;
        };
        let Some(offset) = FixedOffset::east_opt(formatter_offset_seconds(env, this)) else {
            return nil;
        };
        let Some(date) = offset.from_local_datetime(&date).single() else {
            return nil;
        };
        date.timestamp() as f64 + f64::from(date.timestamp_subsec_nanos()) / 1_000_000_000.0
    };
    msg_class![env; NSDate dateWithTimeIntervalSince1970:timestamp]
}

@end

};

fn formatter_format(env: &mut crate::Environment, formatter: id) -> Option<String> {
    let date_format = env
        .objc
        .borrow::<NSDateFormatterHostObject>(formatter)
        .date_format?;
    Some(ns_string::to_rust_string(env, date_format).to_string())
}

fn formatter_offset_seconds(env: &mut crate::Environment, formatter: id) -> i32 {
    let time_zone = env
        .objc
        .borrow::<NSDateFormatterHostObject>(formatter)
        .time_zone;
    if time_zone == nil {
        current_local_timezone_offset_seconds()
    } else {
        msg![env; time_zone secondsFromGMT]
    }
}

fn translate_date_format(format: &str) -> Option<String> {
    let mut out = String::new();
    let mut chars = format.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\'' {
            while let Some(quoted) = chars.next() {
                if quoted == '\'' {
                    if chars.peek() == Some(&'\'') {
                        chars.next();
                        out.push('\'');
                    } else {
                        break;
                    }
                } else {
                    out.push(quoted);
                }
            }
            continue;
        }

        let mut count = 1;
        while chars.peek() == Some(&ch) {
            chars.next();
            count += 1;
        }

        match ch {
            'y' | 'Y' => out.push_str(if count == 2 { "%y" } else { "%Y" }),
            'M' => out.push_str(match count {
                1 => "%-m",
                2 => "%m",
                3 => "%b",
                _ => "%B",
            }),
            'd' => out.push_str(if count == 1 { "%-d" } else { "%d" }),
            'H' => out.push_str(if count == 1 { "%-H" } else { "%H" }),
            'h' => out.push_str(if count == 1 { "%-I" } else { "%I" }),
            'm' => out.push_str(if count == 1 { "%-M" } else { "%M" }),
            's' => out.push_str(if count == 1 { "%-S" } else { "%S" }),
            'S' => out.push_str("%.3f"),
            'a' => out.push_str("%p"),
            'Z' => out.push_str("%z"),
            'z' => out.push_str("%Z"),
            'E' => out.push_str(if count <= 3 { "%a" } else { "%A" }),
            other if other.is_ascii_alphabetic() => return None,
            other => {
                for _ in 0..count {
                    out.push(other);
                }
            }
        }
    }
    Some(out)
}
