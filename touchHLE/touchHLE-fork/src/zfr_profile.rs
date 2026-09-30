/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Lightweight profiler for Zombie Farm performance work.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

const REPORT_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Clone, Copy)]
pub enum Category {
    GuestCpuRun = 0,
    EnvironmentRunInner,
    ObjcMsgSend,
    ObjcMsgCacheHit,
    ObjcMsgCacheMiss,
    ZombiePreDispatch,
    ObjcImpCall,
    ZombiePostDispatch,
    RunLoop,
    TimerFire,
    EaglPresentRenderbuffer,
    EaglPresentFastPath,
    GlPresentFrame,
    GlSwapWindow,
}

const CATEGORY_COUNT: usize = 14;

const CATEGORY_NAMES: [&str; CATEGORY_COUNT] = [
    "guest_cpu_run",
    "environment_run_inner",
    "objc_msg_send",
    "objc_msg_cache_hit",
    "objc_msg_cache_miss",
    "zombie_pre_dispatch",
    "objc_imp_call",
    "zombie_post_dispatch",
    "run_loop",
    "timer_fire",
    "eagl_present_renderbuffer",
    "eagl_present_fast_path",
    "gl_present_frame",
    "gl_swap_window",
];

struct Counter {
    calls: AtomicU64,
    samples: AtomicU64,
    nanos: AtomicU64,
}

impl Counter {
    const fn new() -> Self {
        Self {
            calls: AtomicU64::new(0),
            samples: AtomicU64::new(0),
            nanos: AtomicU64::new(0),
        }
    }
}

#[derive(Clone, Copy, Default)]
struct Snapshot {
    calls: u64,
    samples: u64,
    nanos: u64,
}

static ENABLED: AtomicBool = AtomicBool::new(false);
static START: OnceLock<Instant> = OnceLock::new();
static NEXT_REPORT_NANOS: AtomicU64 = AtomicU64::new(0);
static LAST_SNAPSHOT: OnceLock<Mutex<[Snapshot; CATEGORY_COUNT]>> = OnceLock::new();

static COUNTERS: [Counter; CATEGORY_COUNT] = [
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
    Counter::new(),
];

pub fn init(enabled: bool) {
    if !enabled {
        return;
    }

    START.get_or_init(Instant::now);
    LAST_SNAPSHOT.get_or_init(|| Mutex::new([Snapshot::default(); CATEGORY_COUNT]));
    NEXT_REPORT_NANOS.store(REPORT_INTERVAL.as_nanos() as u64, Ordering::Relaxed);
    ENABLED.store(true, Ordering::Relaxed);
    echo!("touchHLE ZFR profile: enabled, reporting every 5 seconds");
}

pub fn is_enabled() -> bool {
    ENABLED.load(Ordering::Relaxed)
}

pub fn scope(category: Category) -> Scope {
    if !is_enabled() {
        return Scope {
            category,
            start: None,
        };
    }

    let counter = &COUNTERS[category as usize];
    let call = counter.calls.fetch_add(1, Ordering::Relaxed) + 1;
    let sample_every = match category {
        Category::GuestCpuRun
        | Category::EnvironmentRunInner
        | Category::ObjcMsgSend
        | Category::ObjcImpCall => 1024,
        Category::ZombiePreDispatch | Category::ZombiePostDispatch => 256,
        _ => 1,
    };
    Scope {
        category,
        start: call.is_multiple_of(sample_every).then(Instant::now),
    }
}

pub fn count(category: Category) {
    if !is_enabled() {
        return;
    }
    let counter = &COUNTERS[category as usize];
    counter.calls.fetch_add(1, Ordering::Relaxed);
}

pub struct Scope {
    category: Category,
    start: Option<Instant>,
}

impl Drop for Scope {
    fn drop(&mut self) {
        if let Some(start) = self.start {
            add_sample(self.category, start.elapsed());
        }
    }
}

fn add_sample(category: Category, elapsed: Duration) {
    let counter = &COUNTERS[category as usize];
    counter.samples.fetch_add(1, Ordering::Relaxed);
    counter
        .nanos
        .fetch_add(elapsed.as_nanos() as u64, Ordering::Relaxed);
}

pub fn maybe_report() {
    if !is_enabled() {
        return;
    }

    let Some(start) = START.get() else {
        return;
    };
    let elapsed_nanos = start.elapsed().as_nanos() as u64;
    let next = NEXT_REPORT_NANOS.load(Ordering::Relaxed);
    if elapsed_nanos < next {
        return;
    }
    if NEXT_REPORT_NANOS
        .compare_exchange(
            next,
            elapsed_nanos + REPORT_INTERVAL.as_nanos() as u64,
            Ordering::Relaxed,
            Ordering::Relaxed,
        )
        .is_ok()
    {
        report("periodic");
    }
}

pub fn final_report() {
    if is_enabled() {
        report("final");
    }
}

fn report(label: &str) {
    let elapsed = START
        .get()
        .map_or(0.0, |start| start.elapsed().as_secs_f64());
    let mut current = [Snapshot::default(); CATEGORY_COUNT];
    for (index, counter) in COUNTERS.iter().enumerate() {
        current[index] = Snapshot {
            calls: counter.calls.load(Ordering::Relaxed),
            samples: counter.samples.load(Ordering::Relaxed),
            nanos: counter.nanos.load(Ordering::Relaxed),
        };
    }

    let mut last = LAST_SNAPSHOT
        .get_or_init(|| Mutex::new([Snapshot::default(); CATEGORY_COUNT]))
        .lock()
        .unwrap();

    echo!("touchHLE ZFR profile ({label}, {:.1}s elapsed):", elapsed);
    echo!(
        "{:<28} {:>10} {:>10} {:>12} {:>12} {:>12}",
        "category",
        "calls",
        "samples",
        "est_total_ms",
        "est_delta_ms",
        "avg_us"
    );
    for index in 0..CATEGORY_COUNT {
        let snapshot = current[index];
        let previous = last[index];
        let delta_calls = snapshot.calls.saturating_sub(previous.calls);
        let delta_samples = snapshot.samples.saturating_sub(previous.samples);
        let delta_nanos = snapshot.nanos.saturating_sub(previous.nanos);
        let estimated_total_nanos = if snapshot.samples == 0 {
            0
        } else {
            snapshot.nanos.saturating_mul(snapshot.calls) / snapshot.samples
        };
        let estimated_delta_nanos = if delta_samples == 0 {
            0
        } else {
            delta_nanos.saturating_mul(delta_calls) / delta_samples
        };
        let avg_us = if snapshot.samples == 0 {
            0.0
        } else {
            snapshot.nanos as f64 / snapshot.samples as f64 / 1_000.0
        };
        echo!(
            "{:<28} {:>10} {:>10} {:>12.3} {:>12.3} {:>12.3}",
            CATEGORY_NAMES[index],
            snapshot.calls,
            snapshot.samples,
            estimated_total_nanos as f64 / 1_000_000.0,
            estimated_delta_nanos as f64 / 1_000_000.0,
            avg_us
        );
    }

    *last = current;
}
