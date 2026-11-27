/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Time things including `CFAbsoluteTime`.

use crate::dyld::{export_c_func, FunctionExports};
use crate::frameworks::core_foundation::CFTypeRef;
use crate::frameworks::foundation::NSTimeInterval;
use crate::libc::time::emulated_system_time;
use crate::mem::SafeRead;
use crate::objc::{id, msg, msg_class, nil};
use crate::{impl_GuestRet_for_large_struct, Environment};
use chrono::{Datelike, Timelike};
use std::ops::Add;
use std::time::{Duration, SystemTime};

/// Seconds between Unix and Apple's epochs
pub const SECS_FROM_UNIX_TO_APPLE_EPOCHS: u64 = 978_307_200;

/// The absolute reference date is 1 Jan 2001 00:00:00 GMT
pub fn apple_epoch() -> SystemTime {
    SystemTime::UNIX_EPOCH.add(Duration::from_secs(SECS_FROM_UNIX_TO_APPLE_EPOCHS))
}

pub fn absolute_time(time: SystemTime) -> f64 {
    match time.duration_since(apple_epoch()) {
        Ok(interval) => interval.as_secs_f64(),
        Err(before) => -before.duration().as_secs_f64(),
    }
}

pub fn system_time(at: f64) -> SystemTime {
    let duration = Duration::from_secs_f64(at.abs());
    if at < 0.0 {
        apple_epoch() - duration
    } else {
        apple_epoch() + duration
    }
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
    absolute_time(emulated_system_time())
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
    let mut unix_seconds = SECS_FROM_UNIX_TO_APPLE_EPOCHS as f64 + at.floor();
    if tz != nil {
        let offset: i32 = msg![env; (tz as id) secondsFromGMT];
        unix_seconds += f64::from(offset);
    }
    let date = chrono::DateTime::from_timestamp(unix_seconds as i64, 0)
        .expect("Gregorian date outside supported calendar");
    CFGregorianDate {
        year: date.year(),
        month: date.month() as i8,
        day: date.day() as i8,
        hours: date.hour() as i8,
        minutes: date.minute() as i8,
        seconds: f64::from(date.second()) + (at - at.floor()),
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

#[cfg(test)]
mod epoch_tests {
    use super::*;

    #[test]
    fn negative_and_positive_reference_dates_round_trip() {
        for at in [
            -978_307_200.0,
            -31_622_400.0,
            -0.25,
            0.0,
            0.25,
            31_536_000.0,
        ] {
            assert_eq!(absolute_time(system_time(at)), at);
        }
    }
}
