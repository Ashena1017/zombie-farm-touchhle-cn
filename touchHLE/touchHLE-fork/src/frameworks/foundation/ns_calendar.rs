/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSCalendar` and `NSDateComponents`.

use super::{ns_string, NSInteger, NSTimeInterval, NSUInteger};
use crate::dyld::{ConstantExports, HostConstant};
use crate::libc::time::{
    calendar_date_to_timestamp, current_local_timezone_offset_seconds, timestamp_to_calendar_date,
    tm,
};
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject,
    NSZonePtr,
};
use chrono::{DateTime, Months, NaiveDateTime, TimeDelta, Utc};

const NSGregorianCalendar: &str = "NSGregorianCalendar";
const NSUndefinedDateComponent: NSInteger = NSInteger::MAX;

const NSEraCalendarUnit: NSUInteger = 1 << 1;
const NSYearCalendarUnit: NSUInteger = 1 << 2;
const NSMonthCalendarUnit: NSUInteger = 1 << 3;
const NSDayCalendarUnit: NSUInteger = 1 << 4;
const NSHourCalendarUnit: NSUInteger = 1 << 5;
const NSMinuteCalendarUnit: NSUInteger = 1 << 6;
const NSSecondCalendarUnit: NSUInteger = 1 << 7;
const NSWeekdayCalendarUnit: NSUInteger = 1 << 9;

pub const CONSTANTS: ConstantExports = &[(
    "_NSGregorianCalendar",
    HostConstant::NSString(NSGregorianCalendar),
)];

struct NSCalendarHostObject {
    identifier: id,
    time_zone: id,
}
impl HostObject for NSCalendarHostObject {}

#[derive(Clone, Copy)]
struct NSDateComponentsHostObject {
    era: NSInteger,
    year: NSInteger,
    month: NSInteger,
    day: NSInteger,
    hour: NSInteger,
    minute: NSInteger,
    second: NSInteger,
    weekday: NSInteger,
}
impl Default for NSDateComponentsHostObject {
    fn default() -> Self {
        Self {
            era: NSUndefinedDateComponent,
            year: NSUndefinedDateComponent,
            month: NSUndefinedDateComponent,
            day: NSUndefinedDateComponent,
            hour: NSUndefinedDateComponent,
            minute: NSUndefinedDateComponent,
            second: NSUndefinedDateComponent,
            weekday: NSUndefinedDateComponent,
        }
    }
}
impl HostObject for NSDateComponentsHostObject {}

fn add_months(date_time: NaiveDateTime, months: NSInteger) -> Option<NaiveDateTime> {
    let magnitude = Months::new(months.unsigned_abs());
    if months >= 0 {
        date_time.checked_add_months(magnitude)
    } else {
        date_time.checked_sub_months(magnitude)
    }
}

fn add_defined_time_delta(
    date_time: NaiveDateTime,
    value: NSInteger,
    seconds_per_unit: i64,
) -> Option<NaiveDateTime> {
    if value == NSUndefinedDateComponent {
        return Some(date_time);
    }
    let seconds = i64::from(value).checked_mul(seconds_per_unit)?;
    date_time.checked_add_signed(TimeDelta::seconds(seconds))
}

fn timestamp_by_adding_components(
    timestamp: NSTimeInterval,
    time_zone_offset: i32,
    components: NSDateComponentsHostObject,
) -> Option<NSTimeInterval> {
    if !timestamp.is_finite() {
        return None;
    }

    let whole_seconds = timestamp.floor();
    if whole_seconds < i64::MIN as NSTimeInterval || whole_seconds > i64::MAX as NSTimeInterval {
        return None;
    }
    let fractional_second = timestamp - whole_seconds;
    let local_seconds = (whole_seconds as i64).checked_add(i64::from(time_zone_offset))?;
    let mut date_time = DateTime::<Utc>::from_timestamp(local_seconds, 0)?.naive_utc();

    if components.year != NSUndefinedDateComponent {
        date_time = add_months(date_time, components.year.checked_mul(12)?)?;
    }
    if components.month != NSUndefinedDateComponent {
        date_time = add_months(date_time, components.month)?;
    }
    date_time = add_defined_time_delta(date_time, components.day, 86_400)?;
    date_time = add_defined_time_delta(date_time, components.hour, 3_600)?;
    date_time = add_defined_time_delta(date_time, components.minute, 60)?;
    date_time = add_defined_time_delta(date_time, components.second, 1)?;

    let result_seconds = date_time
        .and_utc()
        .timestamp()
        .checked_sub(i64::from(time_zone_offset))?;
    Some(result_seconds as NSTimeInterval + fractional_second)
}

fn calendar_time_zone_offset_seconds(env: &mut crate::Environment, calendar: id) -> i32 {
    let time_zone = env.objc.borrow::<NSCalendarHostObject>(calendar).time_zone;
    if time_zone == nil {
        current_local_timezone_offset_seconds()
    } else {
        msg![env; time_zone secondsFromGMT]
    }
}

fn components_from_timestamp(env: &mut crate::Environment, timestamp: i32, offset: i32) -> id {
    let local_timestamp = timestamp.saturating_add(offset);
    let date = timestamp_to_calendar_date(local_timestamp);
    let components: id = msg_class![env; NSDateComponents new];
    {
        let host_obj = env
            .objc
            .borrow_mut::<NSDateComponentsHostObject>(components);
        host_obj.era = 1;
        host_obj.year = date.tm_year + 1900;
        host_obj.month = date.tm_mon + 1;
        host_obj.day = date.tm_mday;
        host_obj.hour = date.tm_hour;
        host_obj.minute = date.tm_min;
        host_obj.second = date.tm_sec;
        // 1 = Sunday in NSCalendar.
        host_obj.weekday = 1 + (local_timestamp.div_euclid(86_400) + 4).rem_euclid(7);
    }
    autorelease(env, components)
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSCalendar: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSCalendarHostObject {
        identifier: nil,
        time_zone: nil,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)currentCalendar {
    let identifier = ns_string::get_static_str(env, NSGregorianCalendar);
    let calendar: id = msg![env; this alloc];
    let calendar: id = msg![env; calendar initWithCalendarIdentifier:identifier];
    autorelease(env, calendar)
}

+ (id)calendarWithIdentifier:(id)identifier {
    let calendar: id = msg![env; this alloc];
    let calendar: id = msg![env; calendar initWithCalendarIdentifier:identifier];
    autorelease(env, calendar)
}

- (id)initWithCalendarIdentifier:(id)identifier {
    retain(env, identifier);
    env.objc.borrow_mut::<NSCalendarHostObject>(this).identifier = identifier;
    this
}

- (())dealloc {
    let NSCalendarHostObject {
        identifier,
        time_zone,
    } = std::mem::replace(
        env.objc.borrow_mut::<NSCalendarHostObject>(this),
        NSCalendarHostObject {
            identifier: nil,
            time_zone: nil,
        },
    );
    release(env, identifier);
    release(env, time_zone);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)calendarIdentifier {
    env.objc.borrow::<NSCalendarHostObject>(this).identifier
}

- (id)timeZone {
    env.objc.borrow::<NSCalendarHostObject>(this).time_zone
}

- (())setTimeZone:(id)time_zone {
    retain(env, time_zone);
    let host_obj = env.objc.borrow_mut::<NSCalendarHostObject>(this);
    let old_time_zone = std::mem::replace(&mut host_obj.time_zone, time_zone);
    release(env, old_time_zone);
}

- (id)components:(NSUInteger)_unit_flags
        fromDate:(id)date {
    let timestamp: NSTimeInterval = msg![env; date timeIntervalSince1970];
    let offset = calendar_time_zone_offset_seconds(env, this);
    components_from_timestamp(env, timestamp as i32, offset)
}

- (NSInteger)component:(NSUInteger)unit
              fromDate:(id)date {
    let components: id = msg![env; this components:unit fromDate:date];
    match unit {
        NSEraCalendarUnit => msg![env; components era],
        NSYearCalendarUnit => msg![env; components year],
        NSMonthCalendarUnit => msg![env; components month],
        NSDayCalendarUnit => msg![env; components day],
        NSHourCalendarUnit => msg![env; components hour],
        NSMinuteCalendarUnit => msg![env; components minute],
        NSSecondCalendarUnit => msg![env; components second],
        NSWeekdayCalendarUnit => msg![env; components weekday],
        _ => NSUndefinedDateComponent,
    }
}

- (id)dateByAddingComponents:(id)components
                      toDate:(id)date
                     options:(NSUInteger)_options {
    if components == nil || date == nil {
        return nil;
    }

    let timestamp: NSTimeInterval = msg![env; date timeIntervalSince1970];
    let time_zone_offset = calendar_time_zone_offset_seconds(env, this);
    let components = *env
        .objc
        .borrow::<NSDateComponentsHostObject>(components);
    let Some(result) = timestamp_by_adding_components(timestamp, time_zone_offset, components)
    else {
        return nil;
    };
    msg_class![env; NSDate dateWithTimeIntervalSince1970:result]
}

- (id)dateFromComponents:(id)components {
    let year: NSInteger = msg![env; components year];
    let month: NSInteger = msg![env; components month];
    let day: NSInteger = msg![env; components day];
    let hour: NSInteger = msg![env; components hour];
    let minute: NSInteger = msg![env; components minute];
    let second: NSInteger = msg![env; components second];
    let tm = tm::from(
        if year == NSUndefinedDateComponent { 2001 } else { year as u16 },
        if month == NSUndefinedDateComponent { 1 } else { month as u8 },
        if day == NSUndefinedDateComponent { 1 } else { day as u8 },
        if hour == NSUndefinedDateComponent { 0 } else { hour as u8 },
        if minute == NSUndefinedDateComponent { 0 } else { minute as u8 },
        if second == NSUndefinedDateComponent { 0 } else { second as u8 },
    );
    let offset = calendar_time_zone_offset_seconds(env, this);
    let timestamp = calendar_date_to_timestamp(tm).saturating_sub(offset);
    let seconds = timestamp as NSTimeInterval;
    msg_class![env; NSDate dateWithTimeIntervalSince1970:seconds]
}

@end

@implementation NSDateComponents: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<NSDateComponentsHostObject>::default(), &mut env.mem)
}

- (id)init {
    this
}

- (NSInteger)era { env.objc.borrow::<NSDateComponentsHostObject>(this).era }
- (())setEra:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).era = value; }
- (NSInteger)year { env.objc.borrow::<NSDateComponentsHostObject>(this).year }
- (())setYear:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).year = value; }
- (NSInteger)month { env.objc.borrow::<NSDateComponentsHostObject>(this).month }
- (())setMonth:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).month = value; }
- (NSInteger)day { env.objc.borrow::<NSDateComponentsHostObject>(this).day }
- (())setDay:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).day = value; }
- (NSInteger)hour { env.objc.borrow::<NSDateComponentsHostObject>(this).hour }
- (())setHour:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).hour = value; }
- (NSInteger)minute { env.objc.borrow::<NSDateComponentsHostObject>(this).minute }
- (())setMinute:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).minute = value; }
- (NSInteger)second { env.objc.borrow::<NSDateComponentsHostObject>(this).second }
- (())setSecond:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).second = value; }
- (NSInteger)weekday { env.objc.borrow::<NSDateComponentsHostObject>(this).weekday }
- (())setWeekday:(NSInteger)value { env.objc.borrow_mut::<NSDateComponentsHostObject>(this).weekday = value; }

@end

};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adding_a_month_clamps_to_the_last_valid_day() {
        let timestamp = calendar_date_to_timestamp(tm::from(2012, 1, 31, 12, 30, 0));
        let components = NSDateComponentsHostObject {
            month: 1,
            ..Default::default()
        };

        let result = timestamp_by_adding_components(timestamp.into(), 0, components).unwrap();
        let date = timestamp_to_calendar_date(result as i32);
        let actual = (
            date.tm_year + 1900,
            date.tm_mon + 1,
            date.tm_mday,
            date.tm_hour,
            date.tm_min,
            date.tm_sec,
        );
        assert_eq!(actual, (2012, 2, 29, 12, 30, 0));
    }

    #[test]
    fn adding_smaller_units_carries_and_preserves_fractional_seconds() {
        let components = NSDateComponentsHostObject {
            day: 1,
            minute: 2,
            second: 3,
            ..Default::default()
        };

        let result = timestamp_by_adding_components(1_000_000.75, 8 * 3_600, components).unwrap();
        assert_eq!(result, 1_000_000.75 + 86_400.0 + 120.0 + 3.0);
    }
}
