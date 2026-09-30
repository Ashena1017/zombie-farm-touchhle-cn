/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Time things including `CFAbsoluteTime`.

use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_foundation::CFTypeRef;
use crate::frameworks::foundation::NSTimeInterval;
use crate::libc::time::{emulated_system_time, time_t, timestamp_to_calendar_date};
use crate::mem::SafeRead;
use crate::objc::{id, msg, msg_class, nil};
use crate::{impl_GuestRet_for_large_struct, Environment};
use std::ops::Add;
use std::time::{Duration, SystemTime};

/// Seconds between Unix and Apple's epochs
pub const SECS_FROM_UNIX_TO_APPLE_EPOCHS: u64 = 978_307_200;

/// The absolute reference date is 1 Jan 2001 00:00:00 GMT
pub fn apple_epoch() -> SystemTime {
    SystemTime::UNIX_EPOCH.add(Duration::from_secs(SECS_FROM_UNIX_TO_APPLE_EPOCHS))
}

pub type CFTimeInterval = NSTimeInterval;
pub type CFAbsoluteTime = CFTimeInterval;

#[derive(Copy, Clone, Debug, PartialEq)]
#[repr(C, packed)]
pub struct CFGregorianDate {
    pub year: i32,    // SInt32
    pub month: i8,    // SInt8
    pub day: i8,      // SInt8
    pub hours: i8,    // SInt8
    pub minutes: i8,  // SInt8
    pub seconds: f64, // double
}
unsafe impl SafeRead for CFGregorianDate {}
impl_GuestRet_for_large_struct!(CFGregorianDate);

/// Absolute time is measured in seconds relative to the absolute reference date
/// of Jan 1 2001 00:00:00 GMT.
fn CFAbsoluteTimeGetCurrent(_env: &mut Environment) -> CFAbsoluteTime {
    emulated_system_time()
        .duration_since(apple_epoch())
        .unwrap()
        .as_secs_f64()
}

type CFTimeZoneRef = CFTypeRef;

fn CFTimeZoneCopySystem(_env: &mut Environment) -> CFTimeZoneRef {
    msg_class![_env; NSTimeZone localTimeZone]
}

pub fn CFAbsoluteTimeGetGregorianDate(
    env: &mut Environment,
    at: CFAbsoluteTime,
    tz: CFTimeZoneRef,
) -> CFGregorianDate {
    let mut time64 = apple_epoch()
        .add(Duration::from_secs_f64(at))
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    if tz != nil {
        let offset: i32 = msg![env; (tz as id) secondsFromGMT];
        time64 = time64.saturating_add_signed(i64::from(offset));
    }
    let time = time64 as time_t;
    let tm = timestamp_to_calendar_date(time);
    CFGregorianDate {
        year: 1900 + tm.tm_year,
        month: (tm.tm_mon + 1) as i8,
        day: tm.tm_mday as i8,
        hours: tm.tm_hour as i8,
        minutes: tm.tm_min as i8,
        seconds: tm.tm_sec.into(),
    }
}

fn CFAbsoluteTimeGetDayOfWeek(env: &mut Environment, at: CFAbsoluteTime, tz: CFTimeZoneRef) -> i32 {
    let mut unix_timestamp = SECS_FROM_UNIX_TO_APPLE_EPOCHS as i64 + at.floor() as i64;
    if tz != nil {
        let offset: i32 = msg![env; (tz as id) secondsFromGMT];
        unix_timestamp += i64::from(offset);
    }
    // 1 = Sunday. The Unix epoch, 1970-01-01, was a Thursday.
    let days_since_unix_epoch = unix_timestamp.div_euclid(86_400);
    1 + (days_since_unix_epoch + 4).rem_euclid(7) as i32
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CFAbsoluteTimeGetCurrent()),
    export_c_func!(CFTimeZoneCopySystem()),
    export_c_func!(CFAbsoluteTimeGetGregorianDate(_, _)),
    export_c_func!(CFAbsoluteTimeGetDayOfWeek(_, _)),
];
