use crate::frameworks::core_foundation::time::SECS_FROM_UNIX_TO_APPLE_EPOCHS;
use crate::frameworks::core_graphics::{CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::{ns_date, ns_string, NSUInteger};
use crate::fs::GuestPath;
use crate::mem::ConstVoidPtr;
use crate::objc::{id, msg_send_no_type_checking, nil, ObjC};
use crate::Environment;
use std::collections::{BTreeMap, VecDeque};
use std::io::{Result as IoResult, Write};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const RECENT_LIMIT: usize = 160;
const HUNGER_RECENT_LIMIT: usize = 2048;

#[derive(Default)]
struct TableState {
    class_name: String,
    direction: Option<u32>,
    view_size: Option<CGSize>,
    content_size: Option<CGSize>,
    content_offset: Option<CGPoint>,
    last_index_from_offset: Option<u32>,
    last_offset_from_index_arg: Option<u32>,
    last_set_index_arg: Option<u32>,
    last_set_index_cell: Option<u32>,
    recent: VecDeque<String>,
}

#[derive(Default)]
struct State {
    tables: BTreeMap<u32, TableState>,
    recent: VecDeque<String>,
    hunger_events: VecDeque<String>,
    cocos_label_texts: BTreeMap<u32, String>,
}

static STATE: OnceLock<Mutex<State>> = OnceLock::new();

#[derive(Clone, Copy, PartialEq, Eq)]
enum DebugMode {
    Off,
    Full,
    Profile,
}

#[derive(Clone, Copy)]
#[repr(usize)]
pub enum ScrollProfileBucket {
    UiTouchMoveInput = 0,
    UiTouchMoveDispatch,
    ObjcTouchMove,
    SetContentOffset,
    ContentOffset,
    ScrollViewDidScroll,
    TableCellAtIndex,
    NumberOfCellsInTable,
    CellClassForTable,
    DequeueCell,
    CellWithIndex,
    AddCellIfNecessary,
    MoveCellOutOfSight,
    EvictCell,
    IndexFromOffset,
    OffsetFromIndex,
    SetIndexForCell,
    TableSizeQuery,
}

const SCROLL_PROFILE_BUCKET_COUNT: usize = ScrollProfileBucket::TableSizeQuery as usize + 1;

struct ScrollProfileCounter {
    calls: AtomicU64,
    nanos: AtomicU64,
}

impl Default for ScrollProfileCounter {
    fn default() -> Self {
        Self {
            calls: AtomicU64::new(0),
            nanos: AtomicU64::new(0),
        }
    }
}

#[derive(Default)]
struct ScrollOffsetStats {
    seen: u64,
    first_x: f32,
    first_y: f32,
    last_x: f32,
    last_y: f32,
    min_x: f32,
    max_x: f32,
    min_y: f32,
    max_y: f32,
    total_abs_dx: f32,
    total_abs_dy: f32,
}

#[derive(Clone, Copy, Default)]
struct IntervalCounter {
    calls: u64,
    nanos: u64,
}

#[derive(Default)]
struct IndexProfileDetail {
    total: IntervalCounter,
    nil_returns: u64,
    returned_cells: BTreeMap<u32, u64>,
}

#[derive(Default)]
struct SetIndexProfileDetail {
    total: IntervalCounter,
    cells: BTreeMap<u32, u64>,
}

#[derive(Default)]
struct CellBuildDetail {
    total: IntervalCounter,
    messages: BTreeMap<String, IntervalCounter>,
}

struct ScrollProfileTableDetail {
    class_name: String,
    selectors: Vec<IntervalCounter>,
    cell_at_index: BTreeMap<u32, IndexProfileDetail>,
    cell_with_index: BTreeMap<u32, IntervalCounter>,
    set_index: BTreeMap<u32, SetIndexProfileDetail>,
    cell_build: BTreeMap<u32, CellBuildDetail>,
}

impl Default for ScrollProfileTableDetail {
    fn default() -> Self {
        Self {
            class_name: String::new(),
            selectors: vec![IntervalCounter::default(); SCROLL_PROFILE_BUCKET_COUNT],
            cell_at_index: BTreeMap::new(),
            cell_with_index: BTreeMap::new(),
            set_index: BTreeMap::new(),
            cell_build: BTreeMap::new(),
        }
    }
}

#[derive(Default)]
struct ScrollProfileDetailState {
    tables: BTreeMap<u32, ScrollProfileTableDetail>,
}

#[derive(Clone, Copy)]
struct CellBuildScope {
    table_receiver: u32,
    index: u32,
}

#[derive(Clone, Copy)]
pub struct ScrollProfileCall {
    bucket: ScrollProfileBucket,
    table_receiver: u32,
    index: Option<u32>,
    cell: Option<u32>,
}

static SCROLL_PROFILE_LAST_REPORT_MS: AtomicU64 = AtomicU64::new(0);
static SCROLL_PROFILE_COUNTERS: OnceLock<Vec<ScrollProfileCounter>> = OnceLock::new();
static SCROLL_PROFILE_OFFSETS: OnceLock<Mutex<ScrollOffsetStats>> = OnceLock::new();
static SCROLL_PROFILE_DETAILS: OnceLock<Mutex<ScrollProfileDetailState>> = OnceLock::new();
static CELL_BUILD_SCOPE_STACK: OnceLock<Mutex<Vec<CellBuildScope>>> = OnceLock::new();

const SCROLL_PROFILE_BUCKETS: &[(ScrollProfileBucket, &str)] = &[
    (ScrollProfileBucket::UiTouchMoveInput, "ui_move_in"),
    (ScrollProfileBucket::UiTouchMoveDispatch, "ui_move_dispatch"),
    (ScrollProfileBucket::ObjcTouchMove, "objc_touch_move"),
    (ScrollProfileBucket::SetContentOffset, "set_offset"),
    (ScrollProfileBucket::ContentOffset, "get_offset"),
    (ScrollProfileBucket::ScrollViewDidScroll, "did_scroll"),
    (ScrollProfileBucket::TableCellAtIndex, "cell_at_index"),
    (ScrollProfileBucket::NumberOfCellsInTable, "cell_count"),
    (ScrollProfileBucket::CellClassForTable, "cell_class"),
    (ScrollProfileBucket::DequeueCell, "dequeue"),
    (ScrollProfileBucket::CellWithIndex, "cell_with_index"),
    (ScrollProfileBucket::AddCellIfNecessary, "add_cell"),
    (ScrollProfileBucket::MoveCellOutOfSight, "move_cell_out"),
    (ScrollProfileBucket::EvictCell, "evict_cell"),
    (ScrollProfileBucket::IndexFromOffset, "index_from_offset"),
    (ScrollProfileBucket::OffsetFromIndex, "offset_from_index"),
    (ScrollProfileBucket::SetIndexForCell, "set_index"),
    (ScrollProfileBucket::TableSizeQuery, "size_query"),
];

pub struct CocosNodeHit {
    pub node: id,
    pub class_name: String,
    pub world_point: CGPoint,
    pub local_point: CGPoint,
    pub world_rect: CGRect,
    pub depth: usize,
    pub summary: String,
}

pub fn running_scene_size(env: &mut Environment) -> Option<CGSize> {
    let scene = get_running_scene(env)?;
    node_size_by_getter(env, scene, "contentSize")
}

fn state() -> &'static Mutex<State> {
    STATE.get_or_init(|| Mutex::new(State::default()))
}

fn debug_mode() -> DebugMode {
    static MODE: OnceLock<DebugMode> = OnceLock::new();
    *MODE.get_or_init(
        || match std::env::var("TOUCHHLE_ZOMBIE_FARM_DEBUG").ok().as_deref() {
            Some("1") | Some("full") => DebugMode::Full,
            Some("profile") => DebugMode::Profile,
            _ => DebugMode::Off,
        },
    )
}

pub fn enabled() -> bool {
    debug_mode() == DebugMode::Full
}

pub fn scroll_profile_enabled() -> bool {
    matches!(debug_mode(), DebugMode::Full | DebugMode::Profile)
}

pub fn scroll_profile_enabled_for_bundle(env: &Environment) -> bool {
    scroll_profile_enabled()
        && env
            .bundle
            .bundle_identifier()
            .starts_with("com.playforge.Z")
}

fn scroll_profile_counters() -> &'static [ScrollProfileCounter] {
    SCROLL_PROFILE_COUNTERS.get_or_init(|| {
        (0..SCROLL_PROFILE_BUCKET_COUNT)
            .map(|_| ScrollProfileCounter::default())
            .collect()
    })
}

fn scroll_profile_offsets() -> &'static Mutex<ScrollOffsetStats> {
    SCROLL_PROFILE_OFFSETS.get_or_init(|| Mutex::new(ScrollOffsetStats::default()))
}

fn scroll_profile_details() -> &'static Mutex<ScrollProfileDetailState> {
    SCROLL_PROFILE_DETAILS.get_or_init(|| Mutex::new(ScrollProfileDetailState::default()))
}

fn cell_build_scope_stack() -> &'static Mutex<Vec<CellBuildScope>> {
    CELL_BUILD_SCOPE_STACK.get_or_init(|| Mutex::new(Vec::new()))
}

pub fn scroll_profile_bucket(class_name: &str, selector_name: &str) -> Option<ScrollProfileBucket> {
    if matches!(
        selector_name,
        "touchesMoved:withEvent:" | "ccTouchMoved:withEvent:" | "ccTouchesMoved:withEvent:"
    ) {
        return Some(ScrollProfileBucket::ObjcTouchMove);
    }

    let table_delegate_selector = matches!(
        selector_name,
        "table:cellAtIndex:" | "numberOfCellsInTable:" | "cellClassForTable:"
    );
    let table_class = class_name.contains("TableView")
        || class_name == "CCScrollView"
        || class_name.ends_with("Cell");
    if !table_class && !table_delegate_selector {
        return None;
    }

    match selector_name {
        "setContentOffset:" => Some(ScrollProfileBucket::SetContentOffset),
        "contentOffset" => Some(ScrollProfileBucket::ContentOffset),
        "scrollViewDidScroll:" => Some(ScrollProfileBucket::ScrollViewDidScroll),
        "table:cellAtIndex:" => Some(ScrollProfileBucket::TableCellAtIndex),
        "numberOfCellsInTable:" => Some(ScrollProfileBucket::NumberOfCellsInTable),
        "cellClassForTable:" => Some(ScrollProfileBucket::CellClassForTable),
        "dequeueCell" => Some(ScrollProfileBucket::DequeueCell),
        "cellWithIndex:" => Some(ScrollProfileBucket::CellWithIndex),
        "_addCellIfNecessary:" => Some(ScrollProfileBucket::AddCellIfNecessary),
        "_moveCellOutOfSight:" => Some(ScrollProfileBucket::MoveCellOutOfSight),
        "_evictCell" => Some(ScrollProfileBucket::EvictCell),
        "_indexFromOffset:" => Some(ScrollProfileBucket::IndexFromOffset),
        "_offsetFromIndex:" => Some(ScrollProfileBucket::OffsetFromIndex),
        "_setIndex:forCell:" => Some(ScrollProfileBucket::SetIndexForCell),
        "setContentSize:" | "setViewSize:" | "contentSize" | "viewSize" | "cellSize" => {
            Some(ScrollProfileBucket::TableSizeQuery)
        }
        _ => None,
    }
}

pub fn begin_scroll_profile_call(
    bucket: ScrollProfileBucket,
    receiver: id,
    class_name: &str,
    selector_name: &str,
    regs: &[u32; 16],
) -> ScrollProfileCall {
    let table_receiver = match selector_name {
        "table:cellAtIndex:" | "numberOfCellsInTable:" | "cellClassForTable:" => regs[2],
        _ => receiver.to_bits(),
    };
    let index = match selector_name {
        "table:cellAtIndex:" => Some(regs[3]),
        "cellWithIndex:" => Some(regs[2]),
        "_offsetFromIndex:" => Some(regs[3]),
        "_setIndex:forCell:" => Some(regs[2]),
        _ => None,
    };
    let cell = match selector_name {
        "_setIndex:forCell:" => Some(regs[3]),
        "_addCellIfNecessary:" | "_moveCellOutOfSight:" => Some(regs[2]),
        _ => None,
    };

    if table_receiver != 0 {
        let mut details = scroll_profile_details().lock().unwrap();
        let table = details.tables.entry(table_receiver).or_default();
        if table.class_name.is_empty() {
            table.class_name = class_name.to_string();
        }
    }

    if !matches!(bucket, ScrollProfileBucket::SetContentOffset) {
        return ScrollProfileCall {
            bucket,
            table_receiver,
            index,
            cell,
        };
    }

    let point = CGPoint {
        x: f32::from_bits(regs[2]),
        y: f32::from_bits(regs[3]),
    };
    let mut stats = scroll_profile_offsets().lock().unwrap();
    if stats.seen == 0 {
        stats.first_x = point.x;
        stats.first_y = point.y;
        stats.min_x = point.x;
        stats.max_x = point.x;
        stats.min_y = point.y;
        stats.max_y = point.y;
    } else {
        stats.total_abs_dx += (point.x - stats.last_x).abs();
        stats.total_abs_dy += (point.y - stats.last_y).abs();
        stats.min_x = stats.min_x.min(point.x);
        stats.max_x = stats.max_x.max(point.x);
        stats.min_y = stats.min_y.min(point.y);
        stats.max_y = stats.max_y.max(point.y);
    }
    stats.last_x = point.x;
    stats.last_y = point.y;
    stats.seen += 1;

    ScrollProfileCall {
        bucket,
        table_receiver,
        index,
        cell,
    }
}

pub fn record_scroll_profile(bucket: ScrollProfileBucket, elapsed: Duration) {
    record_scroll_profile_count(bucket, elapsed, 1);
}

pub fn record_scroll_profile_count(bucket: ScrollProfileBucket, elapsed: Duration, count: u64) {
    if count > 0 {
        let counter = &scroll_profile_counters()[bucket as usize];
        let nanos = elapsed.as_nanos().min(u128::from(u64::MAX)) as u64;
        counter.calls.fetch_add(count, Ordering::Relaxed);
        counter.nanos.fetch_add(nanos, Ordering::Relaxed);
    }
    maybe_log_scroll_profile();
}

fn should_record_cell_build_message(selector_name: &str) -> bool {
    !matches!(
        selector_name,
        "retain"
            | "release"
            | "autorelease"
            | "class"
            | "superclass"
            | "isKindOfClass:"
            | "respondsToSelector:"
            | "conformsToProtocol:"
            | "hash"
    )
}

fn should_record_zombie_relayout_candidate(class_name: &str, selector_name: &str) -> bool {
    let interesting_class = class_name.starts_with("ZombieActor")
        || class_name == "ActorAttachment"
        || class_name == "CCSprite"
        || class_name == "CCSpriteSheet";
    if !interesting_class {
        return false;
    }

    let lower = selector_name.to_ascii_lowercase();
    [
        "init", "sprite", "frame", "attach", "update", "layout", "refresh", "display", "position",
        "scale", "rotation", "anchor", "visible",
    ]
    .iter()
    .any(|keyword| lower.contains(keyword))
}

pub fn begin_cell_build_scope(selector_name: &str, regs: &[u32; 16]) -> bool {
    if selector_name != "table:cellAtIndex:" {
        return false;
    }

    let mut stack = cell_build_scope_stack().lock().unwrap();
    stack.push(CellBuildScope {
        table_receiver: regs[2],
        index: regs[3],
    });
    true
}

pub fn cell_build_scope_active() -> bool {
    !cell_build_scope_stack().lock().unwrap().is_empty()
}

pub fn record_cell_build_message(class_name: &str, selector_name: &str, elapsed: Duration) {
    if selector_name == "table:cellAtIndex:" || !should_record_cell_build_message(selector_name) {
        return;
    }

    let scope = {
        let stack = cell_build_scope_stack().lock().unwrap();
        stack.last().copied()
    };
    let Some(scope) = scope else {
        return;
    };

    let nanos = elapsed.as_nanos().min(u128::from(u64::MAX)) as u64;
    let mut details = scroll_profile_details().lock().unwrap();
    let table = details.tables.entry(scope.table_receiver).or_default();
    let build = table.cell_build.entry(scope.index).or_default();
    build.total.calls += 1;
    build.total.nanos += nanos;
    let key = format!("{class_name} {selector_name}");
    let entry = build.messages.entry(key).or_default();
    entry.calls += 1;
    entry.nanos += nanos;

    if should_record_zombie_relayout_candidate(class_name, selector_name) {
        let trace_key = format!("{class_name} {selector_name}");
        let trace = build
            .messages
            .entry(format!("RELAYOUT {trace_key}"))
            .or_default();
        trace.calls += 1;
        trace.nanos += nanos;
    }
}

pub fn end_cell_build_scope(started: bool) {
    if !started {
        return;
    }
    let mut stack = cell_build_scope_stack().lock().unwrap();
    let _ = stack.pop();
}

pub fn finish_scroll_profile_call(
    call: ScrollProfileCall,
    elapsed: Duration,
    return_value: Option<u32>,
) {
    record_scroll_profile(call.bucket, elapsed);

    if call.table_receiver == 0 {
        return;
    }

    let nanos = elapsed.as_nanos().min(u128::from(u64::MAX)) as u64;
    let mut details = scroll_profile_details().lock().unwrap();
    let table = details.tables.entry(call.table_receiver).or_default();
    let selector_total = &mut table.selectors[call.bucket as usize];
    selector_total.calls += 1;
    selector_total.nanos += nanos;

    match call.bucket {
        ScrollProfileBucket::TableCellAtIndex => {
            let Some(index) = call.index else {
                return;
            };
            let entry = table.cell_at_index.entry(index).or_default();
            entry.total.calls += 1;
            entry.total.nanos += nanos;
            match return_value {
                Some(0) | None => entry.nil_returns += 1,
                Some(cell) => {
                    *entry.returned_cells.entry(cell).or_insert(0) += 1;
                }
            }
        }
        ScrollProfileBucket::CellWithIndex => {
            let Some(index) = call.index else {
                return;
            };
            let entry = table.cell_with_index.entry(index).or_default();
            entry.calls += 1;
            entry.nanos += nanos;
        }
        ScrollProfileBucket::SetIndexForCell => {
            let Some(index) = call.index else {
                return;
            };
            let entry = table.set_index.entry(index).or_default();
            entry.total.calls += 1;
            entry.total.nanos += nanos;
            if let Some(cell) = call.cell {
                *entry.cells.entry(cell).or_insert(0) += 1;
            }
        }
        _ => {}
    }
}

fn current_time_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or(0)
}

fn take_scroll_offset_summary() -> Option<ScrollOffsetStats> {
    let mut stats = scroll_profile_offsets().lock().unwrap();
    if stats.seen == 0 {
        return None;
    }
    Some(std::mem::take(&mut *stats))
}

fn take_scroll_profile_detail_state() -> ScrollProfileDetailState {
    let mut details = scroll_profile_details().lock().unwrap();
    std::mem::take(&mut *details)
}

fn format_millis(nanos: u64) -> String {
    format!("{:.1}ms", nanos as f64 / 1_000_000.0)
}

fn format_top_cell_at_index(table: &ScrollProfileTableDetail) -> Option<String> {
    let mut rows: Vec<_> = table.cell_at_index.iter().collect();
    rows.sort_by_key(|(_, detail)| std::cmp::Reverse(detail.total.nanos));
    let parts: Vec<_> = rows
        .into_iter()
        .take(5)
        .map(|(index, detail)| {
            format!(
                "{}:{}/{} cells={} nil={}",
                index,
                detail.total.calls,
                format_millis(detail.total.nanos),
                detail.returned_cells.len(),
                detail.nil_returns
            )
        })
        .collect();
    (!parts.is_empty()).then(|| parts.join(" "))
}

fn format_top_interval_map(map: &BTreeMap<u32, IntervalCounter>) -> Option<String> {
    let mut rows: Vec<_> = map.iter().collect();
    rows.sort_by_key(|(_, detail)| std::cmp::Reverse(detail.nanos));
    let parts: Vec<_> = rows
        .into_iter()
        .take(5)
        .map(|(index, detail)| {
            format!("{}:{}/{}", index, detail.calls, format_millis(detail.nanos))
        })
        .collect();
    (!parts.is_empty()).then(|| parts.join(" "))
}

fn format_top_set_index(table: &ScrollProfileTableDetail) -> Option<String> {
    let mut rows: Vec<_> = table.set_index.iter().collect();
    rows.sort_by_key(|(_, detail)| std::cmp::Reverse(detail.total.nanos));
    let parts: Vec<_> = rows
        .into_iter()
        .take(5)
        .map(|(index, detail)| {
            format!(
                "{}:{}/{} cells={}",
                index,
                detail.total.calls,
                format_millis(detail.total.nanos),
                detail.cells.len()
            )
        })
        .collect();
    (!parts.is_empty()).then(|| parts.join(" "))
}

fn format_top_cell_build_messages(detail: &CellBuildDetail) -> Option<String> {
    let mut rows: Vec<_> = detail.messages.iter().collect();
    rows.sort_by_key(|(_, counter)| std::cmp::Reverse(counter.nanos));
    let parts: Vec<_> = rows
        .into_iter()
        .take(5)
        .map(|(key, counter)| format!("{}:{}/{}", key, counter.calls, format_millis(counter.nanos)))
        .collect();
    (!parts.is_empty()).then(|| parts.join(" "))
}

fn format_top_cell_relayout_messages(detail: &CellBuildDetail) -> Option<String> {
    let mut rows: Vec<_> = detail
        .messages
        .iter()
        .filter(|(key, _)| key.starts_with("RELAYOUT "))
        .collect();
    rows.sort_by_key(|(_, counter)| std::cmp::Reverse(counter.nanos));
    let parts: Vec<_> = rows
        .into_iter()
        .take(8)
        .map(|(key, counter)| {
            format!(
                "{}:{}/{}",
                key.trim_start_matches("RELAYOUT "),
                counter.calls,
                format_millis(counter.nanos)
            )
        })
        .collect();
    (!parts.is_empty()).then(|| parts.join(" "))
}

fn format_top_cell_build(table: &ScrollProfileTableDetail) -> Vec<String> {
    let mut rows: Vec<_> = table.cell_build.iter().collect();
    rows.sort_by_key(|(_, detail)| std::cmp::Reverse(detail.total.nanos));
    rows.into_iter()
        .take(3)
        .filter_map(|(index, detail)| {
            let top = format_top_cell_build_messages(detail)?;
            Some(format!(
                "{}:{}/{} {}",
                index,
                detail.total.calls,
                format_millis(detail.total.nanos),
                top
            ))
        })
        .collect()
}

fn format_top_cell_relayout(table: &ScrollProfileTableDetail) -> Vec<String> {
    let mut rows: Vec<_> = table.cell_build.iter().collect();
    rows.sort_by_key(|(_, detail)| std::cmp::Reverse(detail.total.nanos));
    rows.into_iter()
        .take(3)
        .filter_map(|(index, detail)| {
            let top = format_top_cell_relayout_messages(detail)?;
            Some(format!("{index} {top}"))
        })
        .collect()
}

fn maybe_log_scroll_profile() {
    let now = current_time_millis();
    let last = SCROLL_PROFILE_LAST_REPORT_MS.load(Ordering::Relaxed);
    if last == 0 {
        let _ = SCROLL_PROFILE_LAST_REPORT_MS.compare_exchange(
            0,
            now,
            Ordering::Relaxed,
            Ordering::Relaxed,
        );
        return;
    }
    let elapsed_ms = now.saturating_sub(last);
    if elapsed_ms < 1000 {
        return;
    }
    if SCROLL_PROFILE_LAST_REPORT_MS
        .compare_exchange(last, now, Ordering::Relaxed, Ordering::Relaxed)
        .is_err()
    {
        return;
    }

    let counters = scroll_profile_counters();
    let mut total_calls = 0u64;
    let mut total_nanos = 0u64;
    let mut parts = Vec::new();
    for (bucket, name) in SCROLL_PROFILE_BUCKETS {
        let counter = &counters[*bucket as usize];
        let calls = counter.calls.swap(0, Ordering::Relaxed);
        let nanos = counter.nanos.swap(0, Ordering::Relaxed);
        if calls == 0 {
            continue;
        }
        total_calls = total_calls.saturating_add(calls);
        total_nanos = total_nanos.saturating_add(nanos);
        let avg_us = nanos / calls / 1_000;
        parts.push(format!("{name}={calls} avg_us={avg_us}"));
    }
    if total_calls == 0 {
        return;
    }

    log!(
        "ZombieFarm scroll profile: {:.2}s total={} total_ms={:.2} {}",
        elapsed_ms as f64 / 1000.0,
        total_calls,
        total_nanos as f64 / 1_000_000.0,
        parts.join(" ")
    );

    let details = take_scroll_profile_detail_state();
    for (receiver, table) in details.tables {
        let cell_at_index = table.selectors[ScrollProfileBucket::TableCellAtIndex as usize];
        let cell_with_index = table.selectors[ScrollProfileBucket::CellWithIndex as usize];
        let set_index = table.selectors[ScrollProfileBucket::SetIndexForCell as usize];
        let did_scroll = table.selectors[ScrollProfileBucket::ScrollViewDidScroll as usize];
        if cell_at_index.calls == 0
            && cell_with_index.calls == 0
            && set_index.calls == 0
            && did_scroll.calls == 0
        {
            continue;
        }

        log!(
            "ZombieFarm scroll table 0x{:x} {}: did_scroll={}/{} cell_at_index={}/{} cell_with_index={}/{} set_index={}/{}",
            receiver,
            table.class_name,
            did_scroll.calls,
            format_millis(did_scroll.nanos),
            cell_at_index.calls,
            format_millis(cell_at_index.nanos),
            cell_with_index.calls,
            format_millis(cell_with_index.nanos),
            set_index.calls,
            format_millis(set_index.nanos),
        );

        if let Some(top) = format_top_cell_at_index(&table) {
            log!(
                "ZombieFarm scroll table 0x{:x} top cell_at_index {}",
                receiver,
                top
            );
        }
        if let Some(top) = format_top_interval_map(&table.cell_with_index) {
            log!(
                "ZombieFarm scroll table 0x{:x} top cell_with_index {}",
                receiver,
                top
            );
        }
        if let Some(top) = format_top_set_index(&table) {
            log!(
                "ZombieFarm scroll table 0x{:x} top set_index {}",
                receiver,
                top
            );
        }
        for detail in format_top_cell_build(&table) {
            log!(
                "ZombieFarm scroll table 0x{:x} cell_build {}",
                receiver,
                detail
            );
        }
        for detail in format_top_cell_relayout(&table) {
            log!(
                "ZombieFarm scroll table 0x{:x} relayout_build {}",
                receiver,
                detail
            );
        }
    }

    if let Some(offsets) = take_scroll_offset_summary() {
        log!(
            "ZombieFarm scroll offsets: set_offset={} first=({:.1},{:.1}) last=({:.1},{:.1}) range_x={:.1}..{:.1} range_y={:.1}..{:.1} abs_delta=({:.1},{:.1})",
            offsets.seen,
            offsets.first_x,
            offsets.first_y,
            offsets.last_x,
            offsets.last_y,
            offsets.min_x,
            offsets.max_x,
            offsets.min_y,
            offsets.max_y,
            offsets.total_abs_dx,
            offsets.total_abs_dy
        );
    }
}

fn push_recent(recent: &mut VecDeque<String>, line: String) {
    if recent.len() >= RECENT_LIMIT {
        recent.pop_front();
    }
    recent.push_back(line);
}

fn push_recent_hunger(recent: &mut VecDeque<String>, line: String) {
    if recent.len() >= HUNGER_RECENT_LIMIT {
        recent.pop_front();
    }
    recent.push_back(line);
}

pub fn record_table_size_return(receiver: id, class_name: &str, selector_name: &str, size: CGSize) {
    if receiver.is_null() || !(class_name.contains("TableView") || class_name == "CCScrollView") {
        return;
    }

    let receiver_bits = receiver.to_bits();
    let mut state = state().lock().unwrap();
    let table = state.tables.entry(receiver_bits).or_default();
    table.class_name = class_name.to_string();
    match selector_name {
        "viewSize" => table.view_size = Some(size),
        "contentSize" => table.content_size = Some(size),
        _ => {}
    }

    let line = format!("[0x{receiver_bits:x} {class_name} {selector_name}] return size={size}");
    push_recent(&mut table.recent, line.clone());
    push_recent(&mut state.recent, line);
}

pub fn record_table_point_return(
    receiver: id,
    class_name: &str,
    selector_name: &str,
    point: CGPoint,
) {
    if receiver.is_null() || !(class_name.contains("TableView") || class_name == "CCScrollView") {
        return;
    }

    let receiver_bits = receiver.to_bits();
    let mut state = state().lock().unwrap();
    let table = state.tables.entry(receiver_bits).or_default();
    table.class_name = class_name.to_string();
    if selector_name == "contentOffset" {
        table.content_offset = Some(point);
    }

    let line = format!("[0x{receiver_bits:x} {class_name} {selector_name}] return point={point}");
    push_recent(&mut table.recent, line.clone());
    push_recent(&mut state.recent, line);
}

pub fn record_table_value_return(receiver: id, class_name: &str, selector_name: &str, value: u32) {
    if receiver.is_null() || !(class_name.contains("TableView") || class_name == "CCScrollView") {
        return;
    }

    let receiver_bits = receiver.to_bits();
    let mut state = state().lock().unwrap();
    let table = state.tables.entry(receiver_bits).or_default();
    table.class_name = class_name.to_string();
    match selector_name {
        "direction" => table.direction = Some(value),
        "_indexFromOffset:" => table.last_index_from_offset = Some(value),
        _ => {}
    }

    let line = format!("[0x{receiver_bits:x} {class_name} {selector_name}] return value={value}");
    push_recent(&mut table.recent, line.clone());
    push_recent(&mut state.recent, line);
}

pub fn record_table_args(receiver: id, class_name: &str, selector_name: &str, regs: &[u32; 16]) {
    if receiver.is_null() || !(class_name.contains("TableView") || class_name == "CCScrollView") {
        return;
    }

    let receiver_bits = receiver.to_bits();
    let mut state = state().lock().unwrap();
    let table = state.tables.entry(receiver_bits).or_default();
    table.class_name = class_name.to_string();

    let detail = match selector_name {
        "setContentSize:" => {
            let size = CGSize {
                width: f32::from_bits(regs[2]),
                height: f32::from_bits(regs[3]),
            };
            table.content_size = Some(size);
            format!("arg size={size}")
        }
        "setViewSize:" => {
            let size = CGSize {
                width: f32::from_bits(regs[2]),
                height: f32::from_bits(regs[3]),
            };
            table.view_size = Some(size);
            format!("arg size={size}")
        }
        "setContentOffset:" => {
            let point = CGPoint {
                x: f32::from_bits(regs[2]),
                y: f32::from_bits(regs[3]),
            };
            table.content_offset = Some(point);
            format!("arg point={point}")
        }
        "setDirection:" => {
            table.direction = Some(regs[2]);
            format!("arg value={}", regs[2])
        }
        "_offsetFromIndex:" => {
            // _offsetFromIndex: returns a CGPoint and is therefore normally
            // reached through objc_msgSend_stret. In that ABI r0 is the return
            // pointer, r1/r2 are receiver/selector, and the first real method
            // argument is in r3.
            table.last_offset_from_index_arg = Some(regs[3]);
            format!("arg index={}", regs[3])
        }
        "_setIndex:forCell:" => {
            table.last_set_index_arg = Some(regs[2]);
            table.last_set_index_cell = Some(regs[3]);
            format!("arg index={} cell=0x{:x}", regs[2], regs[3])
        }
        "_addCellIfNecessary:" | "_moveCellOutOfSight:" => {
            format!("arg cell=0x{:x}", regs[2])
        }
        "dequeueCell" | "_evictCell" => "(no args)".to_string(),
        "cellWithIndex:" => format!("arg index={}", regs[2]),
        "_indexFromOffset:" => {
            let point = CGPoint {
                x: f32::from_bits(regs[2]),
                y: f32::from_bits(regs[3]),
            };
            format!("arg point={point}")
        }
        "scrollViewDidScroll:" => format!("arg object=0x{:x}", regs[2]),
        _ => return,
    };

    let line = format!("[0x{receiver_bits:x} {class_name} {selector_name}] {detail}");
    push_recent(&mut table.recent, line.clone());
    push_recent(&mut state.recent, line);
}

pub fn record_layout_event(line: String) {
    let mut state = state().lock().unwrap();
    push_recent(&mut state.recent, line);
}

pub fn record_objc_message(receiver: id, class_name: &str, selector_name: &str, regs: &[u32; 16]) {
    let line = format!(
        "[objc call] [0x{:x} {} {}] r2=0x{:x} r3=0x{:x}",
        receiver.to_bits(),
        class_name,
        selector_name,
        regs[2],
        regs[3],
    );

    let mut state = state().lock().unwrap();
    push_recent(&mut state.recent, line);
}

pub fn should_record_hunger_message(class_name: &str, selector_name: &str) -> bool {
    let is_zombie_actor = class_name.starts_with("ZombieActor");
    let is_zombie_menu = class_name == "ZFZombieMenu";
    let is_game_state = matches!(class_name, "ZFGuiLayer" | "GameState" | "GameData");

    (is_zombie_actor
        && matches!(
            selector_name,
            "hunger" | "hungerLevel" | "setHunger:" | "setEatDate:"
        ))
        || (is_zombie_menu
            && matches!(
                selector_name,
                "displayHunger" | "updateSelectedZombieInfo" | "currentZombie"
            ))
        || (is_game_state
            && matches!(
                selector_name,
                "applyZombieHunger"
                    | "fixZombieHunger"
                    | "saveDate"
                    | "setSaveDate:"
                    | "getServerTime"
                    | "handleTimeResponse:"
                    | "handleResponse:forAction:"
                    | "statusCheckDone"
                    | "startUpChecksComplete"
            ))
}

fn string_object_to_debug(env: &mut Environment, string: id) -> String {
    if string == nil {
        return "nil".to_string();
    }

    let Some(class) = debug_object_class(env, string) else {
        return format!("0x{:x} <invalid object>", string.to_bits());
    };

    let class_name = env
        .objc
        .try_get_class_name(class)
        .unwrap_or("<unknown class>")
        .to_string();
    let string_class = env.objc.get_known_class("NSString", &mut env.mem);
    if env.objc.class_is_subclass_of(class, string_class) {
        let value = ns_string::to_rust_string(env, string);
        return format!("0x{:x} {class_name} {:?}", string.to_bits(), value);
    }

    format!("0x{:x} {class_name}", string.to_bits())
}

fn object_to_debug(env: &Environment, object: id) -> String {
    if object == nil {
        return "nil".to_string();
    }

    if debug_object_class(env, object).is_none() {
        return format!("0x{:x} <invalid object>", object.to_bits());
    }

    format!("0x{:x} {}", object.to_bits(), debug_class_name(env, object))
}

fn date_to_debug(env: &Environment, date: id) -> String {
    let object = object_to_debug(env, date);
    let Some(interval) = ns_date::debug_time_interval(env, date) else {
        return object;
    };
    let unix = interval + SECS_FROM_UNIX_TO_APPLE_EPOCHS as f64;
    format!("{object} ref={interval:.3} unix={unix:.3}")
}

pub fn record_hunger_message(
    env: &Environment,
    receiver: id,
    class_name: &str,
    selector_name: &str,
    regs: &[u32; 16],
) {
    if !should_record_hunger_message(class_name, selector_name) {
        return;
    }

    let detail = match selector_name {
        "setHunger:" => format!("arg hunger={:.3}", f32::from_bits(regs[2])),
        "setEatDate:" | "setSaveDate:" => {
            format!("arg date={}", date_to_debug(env, id::from_bits(regs[2])))
        }
        "handleTimeResponse:" => {
            format!(
                "arg object={}",
                object_to_debug(env, id::from_bits(regs[2]))
            )
        }
        "handleResponse:forAction:" => format!(
            "arg response={} action={}",
            object_to_debug(env, id::from_bits(regs[2])),
            object_to_debug(env, id::from_bits(regs[3]))
        ),
        "setString:" => format!(
            "arg string={}",
            object_to_debug(env, id::from_bits(regs[2]))
        ),
        _ => String::new(),
    };

    let suffix = if detail.is_empty() {
        String::new()
    } else {
        format!(" {detail}")
    };
    let line = format!(
        "[call] [{} {}] receiver={}{}",
        class_name,
        selector_name,
        object_to_debug(env, receiver),
        suffix
    );

    let mut state = state().lock().unwrap();
    push_recent_hunger(&mut state.hunger_events, line);
}

pub fn record_hunger_return(
    env: &Environment,
    receiver: id,
    class_name: &str,
    selector_name: &str,
) {
    if !should_record_hunger_message(class_name, selector_name) {
        return;
    }

    let detail = match selector_name {
        "hunger" => format!("return hunger={:.3}", f32::from_bits(env.cpu.regs()[0])),
        "hungerLevel" => format!("return hungerLevel={}", env.cpu.regs()[0]),
        "eatDate" | "currentZombie" | "saveDate" => {
            format!(
                "return object={}",
                date_to_debug(env, id::from_bits(env.cpu.regs()[0]))
            )
        }
        _ => String::new(),
    };

    let suffix = if detail.is_empty() {
        String::new()
    } else {
        format!(" {detail}")
    };
    let line = format!(
        "[return] [{} {}] receiver={}{}",
        class_name,
        selector_name,
        object_to_debug(env, receiver),
        suffix
    );

    let mut state = state().lock().unwrap();
    push_recent_hunger(&mut state.hunger_events, line);
}

pub fn should_record_apply_trace_message(class_name: &str, selector_name: &str) -> bool {
    let interesting_class = class_name.starts_with("ZombieActor")
        || matches!(
            class_name,
            "NSDate"
                | "ActiveProfileStatus"
                | "GameState"
                | "GameData"
                | "PlayerProfile"
                | "ZFActorManager"
                | "ZFGuiLayer"
                | "_touchHLE_NSArray"
                | "_touchHLE_NSMutableArray"
        );
    let interesting_selector = matches!(
        selector_name,
        "actorList"
            | "addTimeInterval:"
            | "applyZombieHunger"
            | "count"
            | "date"
            | "eatDate"
            | "gameState"
            | "getActivePlayer"
            | "getBeginningOfTheDayFromDate:"
            | "handleTimeResponse:"
            | "hunger"
            | "isEqual:"
            | "isValid"
            | "latestStatus"
            | "objectAtIndex:"
            | "saveDate"
            | "serverDate"
            | "setEatDate:"
            | "setHunger:"
            | "setSaveDate:"
            | "timeIntervalSinceDate:"
            | "timeIntervalSinceNow"
            | "timeIntervalSinceReferenceDate"
            | "zfGameData"
    );
    interesting_class && interesting_selector
}

fn f64_arg_from_regs(regs: &[u32; 16], start: usize) -> f64 {
    let mut bytes = [0u8; 8];
    bytes[0..4].copy_from_slice(&regs[start].to_le_bytes());
    bytes[4..8].copy_from_slice(&regs[start + 1].to_le_bytes());
    f64::from_bits(u64::from_le_bytes(bytes))
}

fn f64_return_from_regs(regs: &[u32; 16]) -> f64 {
    f64_arg_from_regs(regs, 0)
}

pub fn record_apply_trace_message(
    env: &Environment,
    receiver: id,
    class_name: &str,
    selector_name: &str,
    regs: &[u32; 16],
) {
    if !should_record_apply_trace_message(class_name, selector_name) {
        return;
    }

    let detail = match selector_name {
        "addTimeInterval:" => format!(" arg seconds={:.3}", f64_arg_from_regs(regs, 2)),
        "getBeginningOfTheDayFromDate:"
        | "isEqual:"
        | "setEatDate:"
        | "setSaveDate:"
        | "timeIntervalSinceDate:" => {
            format!(" arg object={}", date_to_debug(env, id::from_bits(regs[2])))
        }
        "objectAtIndex:" => format!(" arg index={}", regs[2]),
        "setHunger:" => format!(" arg hunger={:.3}", f32::from_bits(regs[2])),
        _ => String::new(),
    };

    let line = format!(
        "[apply call] [{} {}] receiver={}{}",
        class_name,
        selector_name,
        object_to_debug(env, receiver),
        detail
    );
    let mut state = state().lock().unwrap();
    push_recent_hunger(&mut state.hunger_events, line);
}

pub fn record_apply_trace_return(
    env: &Environment,
    receiver: id,
    class_name: &str,
    selector_name: &str,
) {
    if !should_record_apply_trace_message(class_name, selector_name) {
        return;
    }

    let detail = match selector_name {
        "count" => format!(" return count={}", env.cpu.regs()[0]),
        "hunger" => format!(" return hunger={:.3}", f32::from_bits(env.cpu.regs()[0])),
        "isEqual:" => format!(" return bool={}", env.cpu.regs()[0]),
        "timeIntervalSinceDate:" | "timeIntervalSinceNow" | "timeIntervalSinceReferenceDate" => {
            format!(
                " return seconds={:.3}",
                f64_return_from_regs(env.cpu.regs())
            )
        }
        "addTimeInterval:"
        | "date"
        | "eatDate"
        | "getBeginningOfTheDayFromDate:"
        | "saveDate"
        | "serverDate" => {
            format!(
                " return date={}",
                date_to_debug(env, id::from_bits(env.cpu.regs()[0]))
            )
        }
        "actorList" | "gameState" | "objectAtIndex:" | "zfGameData" => {
            format!(
                " return object={}",
                object_to_debug(env, id::from_bits(env.cpu.regs()[0]))
            )
        }
        _ => String::new(),
    };

    let line = format!(
        "[apply return] [{} {}] receiver={}{}",
        class_name,
        selector_name,
        object_to_debug(env, receiver),
        detail
    );
    let mut state = state().lock().unwrap();
    push_recent_hunger(&mut state.hunger_events, line);
}

pub fn record_table_object_return(
    receiver: id,
    class_name: &str,
    selector_name: &str,
    object: id,
    object_class_name: Option<&str>,
) {
    let object_bits = object.to_bits();
    let object_desc = match object_class_name {
        Some(name) => format!("0x{object_bits:x} {name}"),
        None if object.is_null() => "nil".to_string(),
        None => format!("0x{object_bits:x} <unknown class>"),
    };

    let line = format!(
        "[0x{:x} {class_name} {selector_name}] return object={object_desc}",
        receiver.to_bits()
    );

    let mut state = state().lock().unwrap();
    if !receiver.is_null() && (class_name.contains("TableView") || class_name == "CCScrollView") {
        let table = state.tables.entry(receiver.to_bits()).or_default();
        table.class_name = class_name.to_string();
        push_recent(&mut table.recent, line.clone());
    }
    push_recent(&mut state.recent, line);
}

pub fn should_record_cocos_label_text(class_name: &str, selector_name: &str) -> bool {
    class_name == "CCLabel"
        && (selector_name == "setString:"
            || selector_name.starts_with("initWithString:")
            || selector_name.starts_with("labelWithString:"))
}

pub fn record_cocos_label_text_return(
    env: &mut Environment,
    receiver: id,
    class_name: &str,
    selector_name: &str,
    regs_before: &[u32; 16],
) {
    if !should_record_cocos_label_text(class_name, selector_name) {
        return;
    }

    let string = id::from_bits(regs_before[2]);
    if string == nil || debug_object_class(env, string).is_none() {
        return;
    }
    let Some(text) = object_string_value_including_empty(env, string) else {
        return;
    };

    let label = if selector_name == "setString:" {
        receiver
    } else {
        id::from_bits(env.cpu.regs()[0])
    };
    if label == nil || debug_object_class(env, label).is_none() {
        return;
    }

    let line = format!(
        "[0x{:x} {class_name} {selector_name}] label=0x{:x} text={:?}",
        receiver.to_bits(),
        label.to_bits(),
        text
    );
    let mut state = state().lock().unwrap();
    state.cocos_label_texts.insert(label.to_bits(), text);
    push_recent(&mut state.recent, line);
}

pub fn write_snapshot(mut writer: impl Write) -> IoResult<()> {
    let state = state().lock().unwrap();

    writeln!(writer, "== Zombie Farm CCTableView Inspector ==")?;
    if state.tables.is_empty() {
        writeln!(writer, "(no CCTableView messages recorded yet)")?;
    }
    for (receiver, table) in &state.tables {
        writeln!(writer)?;
        writeln!(writer, "Table 0x{receiver:x} {}", table.class_name)?;
        writeln!(writer, "  direction: {:?}", table.direction)?;
        writeln!(writer, "  view_size: {:?}", table.view_size)?;
        writeln!(writer, "  content_size: {:?}", table.content_size)?;
        writeln!(writer, "  content_offset: {:?}", table.content_offset)?;
        writeln!(
            writer,
            "  last_index_from_offset: {:?}",
            table.last_index_from_offset
        )?;
        writeln!(
            writer,
            "  last_offset_from_index_arg: {:?}",
            table.last_offset_from_index_arg
        )?;
        writeln!(
            writer,
            "  last_set_index: {:?}, cell: {:?}",
            table.last_set_index_arg.map(|v| format!("{v}")),
            table.last_set_index_cell.map(|v| format!("0x{v:x}"))
        )?;
        writeln!(writer, "  recent:")?;
        for line in &table.recent {
            writeln!(writer, "    {line}")?;
        }
    }

    writeln!(writer)?;
    writeln!(writer, "== Recent Layout Events ==")?;
    for line in &state.recent {
        writeln!(writer, "{line}")?;
    }

    writeln!(writer)?;
    writeln!(writer, "== Recent Hunger Events ==")?;
    for line in &state.hunger_events {
        writeln!(writer, "{line}")?;
    }

    writeln!(writer)?;
    writeln!(writer, "== Recorded Cocos Label Text ==")?;
    if state.cocos_label_texts.is_empty() {
        writeln!(writer, "(none recorded yet)")?;
    }
    for (label, text) in &state.cocos_label_texts {
        writeln!(writer, "0x{label:x} {:?}", text)?;
    }

    Ok(())
}

fn debug_class_name(env: &Environment, object: id) -> String {
    if object == nil {
        return "nil".to_string();
    }
    let Some(class) = debug_object_class(env, object) else {
        return "<invalid object>".to_string();
    };
    env.objc
        .try_get_class_name(class)
        .unwrap_or("<unknown class>")
        .to_string()
}

fn debug_object_class(env: &Environment, object: id) -> Option<id> {
    let bits = object.to_bits();
    if object == nil || bits < env.mem.null_segment_size() || bits % 4 != 0 {
        return None;
    }
    if env
        .mem
        .get_bytes_fallible(ConstVoidPtr::from_bits(bits), 4)
        .is_none()
    {
        return None;
    }

    let class = ObjC::read_isa(object, &env.mem);
    if class == nil || class.to_bits() % 4 != 0 {
        return None;
    }
    env.objc.get_host_object(class)?;
    Some(class)
}

fn debug_object_has_method(env: &Environment, object: id, selector: crate::objc::SEL) -> bool {
    debug_object_class(env, object).is_some()
        && env.objc.object_has_method(&env.mem, object, selector)
}

fn read_object_ivar(env: &Environment, object: id, name: &str) -> Option<id> {
    debug_object_class(env, object)?;
    let ivar = env
        .objc
        .object_lookup_ivar(&env.mem, object, &name.to_string())?;
    Some(env.mem.read(ivar.cast()))
}

fn read_f32_ivar(env: &Environment, object: id, name: &str) -> Option<f32> {
    debug_object_class(env, object)?;
    let ivar = env
        .objc
        .object_lookup_ivar(&env.mem, object, &name.to_string())?;
    Some(env.mem.read(ivar.cast()))
}

fn get_game_state(env: &mut Environment) -> Option<id> {
    let game_state_class = env.objc.get_known_class("GameState", &mut env.mem);
    let game_state_selector = env.objc.lookup_selector("gameState")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_state_class, game_state_selector)
    {
        return None;
    }
    let game_state: id = msg_send_no_type_checking(env, (game_state_class, game_state_selector));
    if game_state == nil {
        return None;
    }
    Some(game_state)
}

fn get_game_data(env: &mut Environment) -> Option<id> {
    let game_state = get_game_state(env)?;

    let zf_game_data_selector = env.objc.lookup_selector("zfGameData")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_state, zf_game_data_selector)
    {
        return None;
    }
    let game_data: id = msg_send_no_type_checking(env, (game_state, zf_game_data_selector));
    if game_data == nil {
        return None;
    }
    Some(game_data)
}

fn get_gui_layer(env: &mut Environment) -> Option<id> {
    let gui_layer_class = env.objc.get_known_class("ZFGuiLayer", &mut env.mem);
    let gui_selector = env.objc.lookup_selector("gui")?;
    if !env
        .objc
        .object_has_method(&env.mem, gui_layer_class, gui_selector)
    {
        return None;
    }
    let gui_layer: id = msg_send_no_type_checking(env, (gui_layer_class, gui_selector));
    (gui_layer != nil).then_some(gui_layer)
}

fn get_running_scene(env: &mut Environment) -> Option<id> {
    let director_class = env.objc.get_known_class("CCDirector", &mut env.mem);
    let shared_director_selector = env.objc.lookup_selector("sharedDirector")?;
    if !env
        .objc
        .object_has_method(&env.mem, director_class, shared_director_selector)
    {
        return None;
    }
    let director: id = msg_send_no_type_checking(env, (director_class, shared_director_selector));
    if director == nil {
        return None;
    }

    let running_scene_selector = env.objc.lookup_selector("runningScene")?;
    if !env
        .objc
        .object_has_method(&env.mem, director, running_scene_selector)
    {
        return None;
    }
    let running_scene: id = msg_send_no_type_checking(env, (director, running_scene_selector));
    (running_scene != nil).then_some(running_scene)
}

fn node_children(env: &mut Environment, node: id) -> Option<(id, NSUInteger)> {
    let children_selector = env.objc.lookup_selector("children")?;
    if !debug_object_has_method(env, node, children_selector) {
        return None;
    }
    let children: id = msg_send_no_type_checking(env, (node, children_selector));
    let count = count_if_collection(env, children)?;
    Some((children, count))
}

fn get_actor_list_from_game_state(env: &mut Environment) -> Option<id> {
    let game_data = get_game_data(env)?;
    let actor_list_selector = env.objc.lookup_selector("actorList")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_data, actor_list_selector)
    {
        return None;
    }
    let actor_list: id = msg_send_no_type_checking(env, (game_data, actor_list_selector));
    (actor_list != nil).then_some(actor_list)
}

fn count_if_collection(env: &mut Environment, object: id) -> Option<NSUInteger> {
    let count_selector = env.objc.lookup_selector("count")?;
    if !debug_object_has_method(env, object, count_selector) {
        return None;
    }
    Some(msg_send_no_type_checking(env, (object, count_selector)))
}

fn object_at_index_if_collection(
    env: &mut Environment,
    object: id,
    index: NSUInteger,
) -> Option<id> {
    let object_at_index_selector = env.objc.lookup_selector("objectAtIndex:")?;
    if !debug_object_has_method(env, object, object_at_index_selector) {
        return None;
    }
    Some(msg_send_no_type_checking(
        env,
        (object, object_at_index_selector, index),
    ))
}

fn object_to_debug_with_count(env: &mut Environment, object: id) -> String {
    let mut description = object_to_debug(env, object);
    if let Some(count) = count_if_collection(env, object) {
        description.push_str(&format!(" count={count}"));
    }
    description
}

fn node_point_by_getter(env: &mut Environment, object: id, selector_name: &str) -> Option<CGPoint> {
    let selector = env.objc.lookup_selector(selector_name)?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector)))
}

fn node_size_by_getter(env: &mut Environment, object: id, selector_name: &str) -> Option<CGSize> {
    let selector = env.objc.lookup_selector(selector_name)?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector)))
}

fn node_f32_by_getter(env: &mut Environment, object: id, selector_name: &str) -> Option<f32> {
    let selector = env.objc.lookup_selector(selector_name)?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector)))
}

fn node_bool_by_getter(env: &mut Environment, object: id, selector_name: &str) -> Option<bool> {
    let selector = env.objc.lookup_selector(selector_name)?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector)))
}

fn node_world_origin(env: &mut Environment, object: id) -> Option<CGPoint> {
    let selector = env.objc.lookup_selector("convertToWorldSpace:")?;
    if !debug_object_has_method(env, object, selector) {
        return None;
    }
    let origin = CGPoint { x: 0.0, y: 0.0 };
    Some(msg_send_no_type_checking(env, (object, selector, origin)))
}

fn node_point_to_local(env: &mut Environment, object: id, point: CGPoint) -> Option<CGPoint> {
    let selector = env.objc.lookup_selector("convertToNodeSpace:")?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector, point)))
}

fn node_point_to_world(env: &mut Environment, object: id, point: CGPoint) -> Option<CGPoint> {
    let selector = env.objc.lookup_selector("convertToWorldSpace:")?;
    debug_object_has_method(env, object, selector)
        .then(|| msg_send_no_type_checking(env, (object, selector, point)))
}

fn point_in_size(point: CGPoint, size: CGSize) -> bool {
    point.x >= 0.0 && point.y >= 0.0 && point.x <= size.width && point.y <= size.height
}

fn rect_from_world_corners(corners: [CGPoint; 4]) -> CGRect {
    let mut min_x = corners[0].x;
    let mut max_x = corners[0].x;
    let mut min_y = corners[0].y;
    let mut max_y = corners[0].y;
    for corner in corners.into_iter().skip(1) {
        min_x = min_x.min(corner.x);
        max_x = max_x.max(corner.x);
        min_y = min_y.min(corner.y);
        max_y = max_y.max(corner.y);
    }
    CGRect {
        origin: CGPoint { x: min_x, y: min_y },
        size: CGSize {
            width: max_x - min_x,
            height: max_y - min_y,
        },
    }
}

fn node_world_rect(env: &mut Environment, node: id, size: CGSize) -> Option<CGRect> {
    let bottom_left = node_point_to_world(env, node, CGPoint { x: 0.0, y: 0.0 })?;
    let bottom_right = node_point_to_world(
        env,
        node,
        CGPoint {
            x: size.width,
            y: 0.0,
        },
    )?;
    let top_left = node_point_to_world(
        env,
        node,
        CGPoint {
            x: 0.0,
            y: size.height,
        },
    )?;
    let top_right = node_point_to_world(
        env,
        node,
        CGPoint {
            x: size.width,
            y: size.height,
        },
    )?;
    Some(rect_from_world_corners([
        bottom_left,
        bottom_right,
        top_left,
        top_right,
    ]))
}

fn inspect_cocos_node_inner(
    env: &mut Environment,
    node: id,
    world_point: CGPoint,
    scene_size: CGSize,
    depth: usize,
    visited: &mut Vec<u32>,
) -> Option<CocosNodeHit> {
    if node == nil || debug_object_class(env, node).is_none() {
        return None;
    }
    let node_bits = node.to_bits();
    if visited.contains(&node_bits) {
        return None;
    }
    visited.push(node_bits);

    let visible = node_bool_by_getter(env, node, "isVisible")
        .or_else(|| node_bool_by_getter(env, node, "visible"))
        .unwrap_or(true);
    if !visible {
        return None;
    }

    let mut best = None;
    if let Some((children, count)) = node_children(env, node) {
        for idx in (0..count.min(256)).rev() {
            let Some(child) = object_at_index_if_collection(env, children, idx) else {
                continue;
            };
            if let Some(hit) =
                inspect_cocos_node_inner(env, child, world_point, scene_size, depth + 1, visited)
            {
                best = Some(hit);
                break;
            }
        }
    }
    if best.is_some() {
        return best;
    }

    let size = node_size_by_getter(env, node, "contentSize")?;
    if size.width <= 0.0 || size.height <= 0.0 {
        return None;
    }
    let local_point = node_point_to_local(env, node, world_point)?;
    if !point_in_size(local_point, size) {
        return None;
    }
    let world_rect = node_world_rect(env, node, size)?;

    let class_name = debug_class_name(env, node).to_string();
    let local_area = size.width * size.height;
    let world_area = world_rect.size.width * world_rect.size.height;
    let scene_area = scene_size.width * scene_size.height;
    let is_near_full_scene =
        scene_area > 0.0 && (local_area >= scene_area * 0.70 || world_area >= scene_area * 0.70);
    let is_known_container = matches!(
        class_name.as_str(),
        "CCMenu" | "CCLayer" | "CCScene" | "ZFFightGameScene" | "ZFFarmGameScene"
    ) || class_name.contains("Delegate")
        || class_name.ends_with("Scene")
        || class_name.ends_with("Layer");
    let is_broad_container =
        is_near_full_scene || is_known_container && local_area >= 1024.0 * 700.0;
    if is_broad_container {
        return None;
    }

    Some(CocosNodeHit {
        node,
        class_name,
        world_point,
        local_point,
        world_rect,
        depth,
        summary: cocos_node_summary(env, node),
    })
}

pub fn inspect_cocos_node_at_points(
    env: &mut Environment,
    points: &[CGPoint],
) -> Option<CocosNodeHit> {
    let scene = get_running_scene(env)?;
    let scene_size = node_size_by_getter(env, scene, "contentSize").unwrap_or(CGSize {
        width: 1024.0,
        height: 768.0,
    });
    let mut best = None;
    for &point in points {
        let mut visited = Vec::new();
        let Some(hit) = inspect_cocos_node_inner(env, scene, point, scene_size, 0, &mut visited)
        else {
            continue;
        };
        let replace = best.as_ref().is_none_or(|best_hit: &CocosNodeHit| {
            hit.depth > best_hit.depth
                || (hit.depth == best_hit.depth
                    && hit.world_rect.size.width * hit.world_rect.size.height
                        < best_hit.world_rect.size.width * best_hit.world_rect.size.height)
        });
        if replace {
            best = Some(hit);
        }
    }
    best
}

pub fn write_cocos_node_detail(
    env: &mut Environment,
    writer: &mut dyn Write,
    node: id,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}0x{:x} {} {}",
        node.to_bits(),
        debug_class_name(env, node),
        cocos_node_summary(env, node)
    )?;
    dump_texture_debug_ivars(env, writer, node, depth + 1)?;
    writeln!(writer, "{indent}Parent chain:")?;
    dump_cocos_parent_chain(env, writer, node, depth + 1)?;
    if let Some(container) = nearest_cocos_cell_container(env, node) {
        writeln!(writer, "{indent}Nearest cell container subtree:")?;
        let mut subtree_visited = Vec::new();
        dump_cocos_node(env, writer, container, depth + 1, &mut subtree_visited)?;
    }
    writeln!(writer, "{indent}Children:")?;
    let mut child_visited = Vec::new();
    dump_cocos_node(env, writer, node, depth + 1, &mut child_visited)?;
    writeln!(writer, "{indent}Text scan:")?;
    let mut visited = Vec::new();
    dump_cocos_text_scan(env, writer, node, depth + 1, 4, &mut visited)
}

fn dump_cocos_parent_chain(
    env: &mut Environment,
    writer: &mut dyn Write,
    node: id,
    depth: usize,
) -> IoResult<()> {
    let mut current = node;
    let mut visited = Vec::new();
    for level in 0..12 {
        if current == nil || debug_object_class(env, current).is_none() {
            break;
        }
        let current_bits = current.to_bits();
        let indent = "  ".repeat(depth);
        if visited.contains(&current_bits) {
            writeln!(writer, "{indent}[{level}] 0x{current_bits:x} <cycle>")?;
            break;
        }
        visited.push(current_bits);
        writeln!(
            writer,
            "{indent}[{level}] 0x{current_bits:x} {} {}",
            debug_class_name(env, current),
            cocos_node_summary(env, current)
        )?;

        let Some(parent) = read_object_ivar(env, current, "parent_") else {
            break;
        };
        if parent == nil {
            break;
        }
        current = parent;
    }
    Ok(())
}

fn nearest_cocos_cell_container(env: &Environment, node: id) -> Option<id> {
    let mut current = node;
    let mut visited = Vec::new();
    for _ in 0..16 {
        if current == nil || debug_object_class(env, current).is_none() {
            return None;
        }
        let bits = current.to_bits();
        if visited.contains(&bits) {
            return None;
        }
        visited.push(bits);

        if debug_class_name(env, current) == "CCColorLayer" {
            return Some(current);
        }

        let Some(parent) = read_object_ivar(env, current, "parent_") else {
            return None;
        };
        if parent == nil {
            return None;
        }
        current = parent;
    }
    None
}

pub fn write_nearby_cocos_text(
    env: &mut Environment,
    writer: &mut dyn Write,
    selected_rect: CGRect,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    let search_rect = expand_rect(selected_rect, 120.0);
    writeln!(
        writer,
        "{indent}Nearby Cocos text candidates (world rect expanded by 120): {}",
        rect_to_debug(search_rect)
    )?;

    let Some(scene) = get_running_scene(env) else {
        writeln!(writer, "{indent}  (no running scene)")?;
        return Ok(());
    };

    let mut visited = Vec::new();
    let mut found = 0usize;
    dump_nearby_cocos_text_inner(
        env,
        writer,
        scene,
        search_rect,
        depth + 1,
        0,
        &mut visited,
        &mut found,
    )?;
    if found == 0 {
        writeln!(writer, "{indent}  (none found)")?;
    }
    Ok(())
}

fn object_is_ns_string(env: &mut Environment, object: id) -> bool {
    let Some(class) = debug_object_class(env, object) else {
        return false;
    };
    let string_class = env.objc.get_known_class("NSString", &mut env.mem);
    env.objc.class_is_subclass_of(class, string_class)
}

fn object_is_known_class(env: &mut Environment, object: id, known_class_name: &str) -> bool {
    let Some(class) = debug_object_class(env, object) else {
        return false;
    };
    let known_class = env.objc.get_known_class(known_class_name, &mut env.mem);
    env.objc.class_is_subclass_of(class, known_class)
}

fn object_is_ns_dictionary(env: &mut Environment, object: id) -> bool {
    object_is_known_class(env, object, "NSDictionary")
}

fn object_string_value(env: &mut Environment, object: id) -> Option<String> {
    if !object_is_ns_string(env, object) {
        return None;
    }
    let value = ns_string::to_rust_string(env, object).into_owned();
    (!value.is_empty()).then_some(value)
}

fn object_string_value_including_empty(env: &mut Environment, object: id) -> Option<String> {
    if !object_is_ns_string(env, object) {
        return None;
    }
    Some(ns_string::to_rust_string(env, object).into_owned())
}

fn object_scalar_debug_value(env: &mut Environment, object: id) -> Option<String> {
    if object == nil || debug_object_class(env, object).is_none() {
        return None;
    }
    if let Some(text) = object_string_value_including_empty(env, object) {
        return Some(format!("{text:?} ({})", object_to_debug(env, object)));
    }
    if object_is_known_class(env, object, "NSNumber") {
        let Some(selector) = env.objc.lookup_selector("stringValue") else {
            return Some(object_to_debug(env, object));
        };
        if !debug_object_has_method(env, object, selector) {
            return Some(object_to_debug(env, object));
        }
        let string: id = msg_send_no_type_checking(env, (object, selector));
        if let Some(text) = object_string_value_including_empty(env, string) {
            return Some(format!("{text} ({})", object_to_debug(env, object)));
        }
    }
    None
}

fn object_number_f64(env: &mut Environment, object: id) -> Option<f64> {
    if object == nil || debug_object_class(env, object).is_none() {
        return None;
    }
    if object_is_known_class(env, object, "NSNumber") {
        let selector = env.objc.lookup_selector("doubleValue")?;
        if debug_object_has_method(env, object, selector) {
            return Some(msg_send_no_type_checking(env, (object, selector)));
        }
    }
    object_string_value_including_empty(env, object).and_then(|text| text.parse().ok())
}

fn format_duration_seconds(seconds: f64) -> String {
    let seconds = seconds.max(0.0).round() as u64;
    let days = seconds / 86_400;
    let hours = (seconds % 86_400) / 3_600;
    let minutes = (seconds % 3_600) / 60;
    let seconds = seconds % 60;

    let mut parts = Vec::new();
    if days > 0 {
        parts.push(format!("{days}d"));
    }
    if hours > 0 {
        parts.push(format!("{hours}h"));
    }
    if minutes > 0 {
        parts.push(format!("{minutes}m"));
    }
    if parts.is_empty() || seconds > 0 {
        parts.push(format!("{seconds}s"));
    }
    parts.join(" ")
}

fn object_context_debug_value(env: &mut Environment, object: id) -> String {
    let mut description = object_scalar_debug_value(env, object)
        .unwrap_or_else(|| object_to_debug_with_count(env, object));
    if let Some(text) = recorded_cocos_label_text(object) {
        description.push_str(&format!(" recorded_text={text:?}"));
    }
    description
}

fn dump_dictionary_common_fields(
    env: &mut Environment,
    writer: &mut dyn Write,
    dictionary: id,
    depth: usize,
) -> IoResult<()> {
    let Some(all_keys_selector) = env.objc.lookup_selector("allKeys") else {
        return Ok(());
    };
    let Some(object_for_key_selector) = env.objc.lookup_selector("objectForKey:") else {
        return Ok(());
    };
    if !debug_object_has_method(env, dictionary, all_keys_selector)
        || !debug_object_has_method(env, dictionary, object_for_key_selector)
    {
        return Ok(());
    }

    let keys: id = msg_send_no_type_checking(env, (dictionary, all_keys_selector));
    let Some(count) = count_if_collection(env, keys) else {
        return Ok(());
    };

    let mut fields = Vec::new();
    for idx in 0..count.min(48) {
        let Some(key) = object_at_index_if_collection(env, keys, idx) else {
            continue;
        };
        let Some(key_name) = object_string_value_including_empty(env, key) else {
            continue;
        };
        if !dictionary_key_looks_common_field(&key_name) {
            continue;
        }

        let value: id = msg_send_no_type_checking(env, (dictionary, object_for_key_selector, key));
        if value == nil || debug_object_class(env, value).is_none() {
            continue;
        }
        let mut description = object_context_debug_value(env, value);
        if dictionary_key_looks_duration_field(&key_name) {
            if let Some(seconds) = object_number_f64(env, value) {
                description.push_str(&format!(" ({})", format_duration_seconds(seconds)));
            }
        }
        fields.push(format!("{key_name}={description}"));
    }
    if fields.is_empty() {
        return Ok(());
    }
    let indent = "  ".repeat(depth);
    writeln!(writer, "{indent}common fields: {}", fields.join(", "))
}

fn dictionary_key_looks_common_field(key: &str) -> bool {
    let key = key.to_ascii_lowercase();
    [
        "id", "key", "name", "title", "display", "info", "desc", "category", "type", "cost",
        "price", "sell", "buy", "value", "coin", "gold", "cash", "reward", "yield", "harvest",
        "grow", "mature", "duration", "time", "xp", "level", "sprite", "image", "icon",
    ]
    .iter()
    .any(|needle| key.contains(needle))
}

fn dictionary_key_looks_duration_field(key: &str) -> bool {
    let key = key.to_ascii_lowercase();
    ["grow", "mature", "duration", "time", "cooldown", "seconds"]
        .iter()
        .any(|needle| key.contains(needle))
}

fn dump_text_getters(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    indent: &str,
) -> IoResult<()> {
    for selector_name in [
        "string",
        "text",
        "title",
        "label",
        "name",
        "displayName",
        "itemName",
        "getString",
        "fontName",
        "font",
        "titleText",
        "labelString",
    ] {
        let Some(selector) = env.objc.lookup_selector(selector_name) else {
            continue;
        };
        if !debug_object_has_method(env, object, selector) {
            continue;
        }
        let value: id = msg_send_no_type_checking(env, (object, selector));
        if let Some(text) = object_string_value(env, value) {
            writeln!(
                writer,
                "{indent}getter {selector_name} => {:?} ({})",
                text,
                object_to_debug(env, value)
            )?;
        } else if value != nil && debug_object_class(env, value).is_some() {
            writeln!(
                writer,
                "{indent}getter {selector_name} => {}",
                object_to_debug(env, value)
            )?;
        }
    }
    Ok(())
}

fn dump_text_ivars(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    for ivar_name in [
        "string",
        "_string",
        "text",
        "_text",
        "title",
        "_title",
        "label",
        "_label",
        "name",
        "_name",
        "displayName",
        "itemName",
        "string_",
        "text_",
        "title_",
        "name_",
        "fontName",
        "fontName_",
        "titleText",
        "labelString",
        "titleLabel",
        "textLabel",
        "nameLabel",
        "descriptionLabel",
        "priceLabel",
        "costLabel",
        "countLabel",
        "label_",
        "m_pLabel",
        "m_pLabelChild",
    ] {
        let Some(value) = read_object_ivar(env, object, ivar_name) else {
            continue;
        };
        if value == nil || debug_object_class(env, value).is_none() {
            continue;
        }
        if let Some(text) = object_string_value(env, value) {
            writeln!(
                writer,
                "{indent}ivar {ivar_name} => {:?} ({})",
                text,
                object_to_debug(env, value)
            )?;
            continue;
        }

        writeln!(
            writer,
            "{indent}ivar {ivar_name} => {}",
            object_to_debug(env, value)
        )?;
        if remaining > 0 {
            dump_cocos_text_scan(env, writer, value, depth + 1, remaining - 1, visited)?;
        }
    }
    Ok(())
}

fn dump_text_collection_ivar(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if remaining == 0 {
        return Ok(());
    }
    let Some(collection) = read_object_ivar(env, object, ivar_name) else {
        return Ok(());
    };
    let Some(count) = count_if_collection(env, collection) else {
        return Ok(());
    };
    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}ivar {ivar_name} collection={} count={}",
        object_to_debug(env, collection),
        count
    )?;
    for idx in 0..count.min(48) {
        let Some(entry) = object_at_index_if_collection(env, collection, idx) else {
            continue;
        };
        if entry == nil || debug_object_class(env, entry).is_none() {
            continue;
        }
        let entry_indent = "  ".repeat(depth + 1);
        writeln!(
            writer,
            "{entry_indent}[{idx}] {}",
            object_to_debug(env, entry)
        )?;
        dump_cocos_text_scan(env, writer, entry, depth + 2, remaining - 1, visited)?;
    }
    Ok(())
}

fn dump_child_text_scan(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if remaining == 0 {
        return Ok(());
    }
    let Some((children, count)) = node_children(env, object) else {
        return Ok(());
    };
    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}children={} count={}",
        object_to_debug(env, children),
        count
    )?;
    for idx in 0..count.min(80) {
        let Some(child) = object_at_index_if_collection(env, children, idx) else {
            continue;
        };
        if child == nil || debug_object_class(env, child).is_none() {
            continue;
        }
        let child_indent = "  ".repeat(depth + 1);
        writeln!(
            writer,
            "{child_indent}[{idx}] 0x{:x} {} {}",
            child.to_bits(),
            debug_class_name(env, child),
            cocos_node_summary(env, child)
        )?;
        dump_cocos_text_scan(env, writer, child, depth + 2, remaining - 1, visited)?;
    }
    Ok(())
}

fn dump_cocos_text_scan(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if object == nil || debug_object_class(env, object).is_none() {
        return Ok(());
    }
    let object_bits = object.to_bits();
    let indent = "  ".repeat(depth);
    if visited.contains(&object_bits) {
        writeln!(writer, "{indent}0x{object_bits:x} <cycle>")?;
        return Ok(());
    }
    visited.push(object_bits);

    writeln!(
        writer,
        "{indent}0x{object_bits:x} {}",
        debug_class_name(env, object)
    )?;
    if let Some(text) = recorded_cocos_label_text(object) {
        writeln!(writer, "{indent}  recorded text => {:?}", text)?;
    }
    if debug_class_name(env, object) == "CCLabel" {
        dump_cocos_label_render_state(env, writer, object, depth + 1)?;
    }
    let class_name = debug_class_name(env, object);
    dump_text_getters(env, writer, object, &format!("{indent}  "))?;
    dump_text_ivars(env, writer, object, depth + 1, remaining, visited)?;
    if class_name_looks_text_related(&class_name) {
        dump_class_text_ivars(env, writer, object, depth + 1)?;
    }
    if class_name_looks_market_context(&class_name) {
        dump_market_context_ivars(env, writer, object, depth + 1, remaining, visited)?;
    }
    for ivar_name in ["children", "attachments", "childAttachments"] {
        dump_text_collection_ivar(
            env,
            writer,
            object,
            ivar_name,
            depth + 1,
            remaining,
            visited,
        )?;
    }
    dump_child_text_scan(env, writer, object, depth + 1, remaining, visited)
}

fn recorded_cocos_label_text(object: id) -> Option<String> {
    let state = state().lock().unwrap();
    state.cocos_label_texts.get(&object.to_bits()).cloned()
}

fn dump_cocos_label_render_state(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    if let Some(font_size) = read_f32_ivar(env, object, "fontSize_") {
        writeln!(writer, "{indent}fontSize_={font_size:.3}")?;
    }
    for ivar_name in ["contentSize_", "dimensions_"] {
        let Some(ivar) = env
            .objc
            .object_lookup_ivar(&env.mem, object, &ivar_name.to_string())
        else {
            continue;
        };
        let value: CGSize = env.mem.read(ivar.cast());
        writeln!(writer, "{indent}{ivar_name}={value}")?;
    }
    if let Some(ivar) = env
        .objc
        .object_lookup_ivar(&env.mem, object, &"rect_".to_string())
    {
        let value: CGRect = env.mem.read(ivar.cast());
        writeln!(writer, "{indent}rect_={:?}", value)?;
    }
    if let Some(texture) = read_object_ivar(env, object, "texture_") {
        writeln!(writer, "{indent}texture_={}", object_to_debug(env, texture))?;
    }
    Ok(())
}

fn dump_class_text_ivars(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
) -> IoResult<()> {
    let Some(class) = debug_object_class(env, object) else {
        return Ok(());
    };

    let mut ivars = env.objc.debug_all_class_ivars_as_strings(class);
    ivars.sort();
    ivars.dedup();
    if ivars.is_empty() {
        return Ok(());
    }

    let indent = "  ".repeat(depth);
    writeln!(writer, "{indent}class ivars: {}", ivars.join(", "))?;
    for ivar_name in ivars
        .iter()
        .filter(|name| ivar_name_looks_text_related(name))
    {
        let Some(value) = read_object_ivar(env, object, ivar_name) else {
            continue;
        };
        if let Some(text) = object_string_value(env, value) {
            writeln!(
                writer,
                "{indent}ivar {ivar_name} => {:?} ({})",
                text,
                object_to_debug(env, value)
            )?;
        } else if value != nil && debug_object_class(env, value).is_some() {
            writeln!(
                writer,
                "{indent}ivar {ivar_name} => {}",
                object_to_debug(env, value)
            )?;
        } else if value != nil {
            writeln!(
                writer,
                "{indent}ivar {ivar_name} raw=0x{:x}",
                value.to_bits()
            )?;
        }
    }
    Ok(())
}

fn dump_market_context_ivars(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if remaining == 0 {
        return Ok(());
    }
    if !visited.contains(&object.to_bits()) {
        visited.push(object.to_bits());
    }
    let Some(class) = debug_object_class(env, object) else {
        return Ok(());
    };

    let class_name = debug_class_name(env, object);
    let mut ivars = env.objc.debug_all_class_ivars_as_strings(class);
    ivars.sort();
    ivars.dedup();

    let mut rows = Vec::new();
    for ivar_name in &ivars {
        if should_skip_market_context_ivar(&ivar_name)
            || !ivar_name_looks_market_context(&class_name, &ivar_name)
        {
            continue;
        }

        let Some(value) = read_object_ivar(env, object, &ivar_name) else {
            continue;
        };
        if value == nil {
            if ivar_name_is_primary_market_context(&ivar_name) {
                rows.push((ivar_name.clone(), value, "nil".to_string()));
            }
            continue;
        }

        if let Some(text) = object_string_value_including_empty(env, value) {
            rows.push((
                ivar_name.clone(),
                value,
                format!("{:?} ({})", text, object_to_debug(env, value)),
            ));
        } else if debug_object_class(env, value).is_some() {
            rows.push((
                ivar_name.clone(),
                value,
                object_context_debug_value(env, value),
            ));
        } else if ivar_name_is_primary_market_context(&ivar_name) {
            rows.push((
                ivar_name.clone(),
                value,
                format!("raw=0x{:x}", value.to_bits()),
            ));
        }
    }

    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}market/item class ivars: {}",
        ivars.join(", ")
    )?;
    if rows.is_empty() {
        return Ok(());
    }

    writeln!(writer, "{indent}market/item context ivars:")?;
    for (ivar_name, value, description) in rows.into_iter().take(32) {
        writeln!(writer, "{indent}  {ivar_name} => {description}")?;
        if debug_class_name(env, value) == "NSInvocation" {
            dump_invocation_debug(env, writer, value, depth + 2)?;
        }
        dump_market_collection_entries(env, writer, value, depth + 2, remaining - 1, visited)?;
        if debug_class_name(env, value).contains("Buyable") {
            dump_child_text_scan(env, writer, value, depth + 2, remaining - 1, visited)?;
        }
        if value == nil
            || visited.contains(&value.to_bits())
            || !debug_object_class(env, value).is_some()
            || object_is_ns_string(env, value)
            || !should_recurse_market_context_object(env, value)
        {
            continue;
        }
        visited.push(value.to_bits());
        dump_market_context_ivars(env, writer, value, depth + 2, remaining - 1, visited)?;
        if class_name_looks_text_related(&debug_class_name(env, value)) {
            dump_class_text_ivars(env, writer, value, depth + 2)?;
        }
    }

    Ok(())
}

fn dump_market_collection_entries(
    env: &mut Environment,
    writer: &mut dyn Write,
    collection: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if collection == nil {
        return Ok(());
    }
    if object_is_ns_dictionary(env, collection) {
        return dump_market_dictionary_entries(env, writer, collection, depth, remaining, visited);
    }
    if remaining == 0 {
        return Ok(());
    }
    let Some(count) = count_if_collection(env, collection) else {
        return Ok(());
    };
    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}entries showing {}/{}:",
        count.min(16),
        count
    )?;
    for idx in 0..count.min(16) {
        let Some(entry) = object_at_index_if_collection(env, collection, idx) else {
            continue;
        };
        let description = object_context_debug_value(env, entry);
        writeln!(writer, "{indent}  [{idx}] {description}")?;
        if entry == nil
            || visited.contains(&entry.to_bits())
            || debug_object_class(env, entry).is_none()
            || object_is_ns_string(env, entry)
            || !should_recurse_market_context_object(env, entry)
        {
            continue;
        }
        if object_is_ns_dictionary(env, entry) {
            dump_market_dictionary_entries(env, writer, entry, depth + 2, remaining - 1, visited)?;
        } else {
            dump_market_context_ivars(env, writer, entry, depth + 2, remaining - 1, visited)?;
        }
        if debug_class_name(env, entry).contains("Buyable") {
            dump_child_text_scan(env, writer, entry, depth + 2, remaining - 1, visited)?;
        }
    }
    Ok(())
}

fn dump_market_dictionary_entries(
    env: &mut Environment,
    writer: &mut dyn Write,
    dictionary: id,
    depth: usize,
    remaining: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if dictionary == nil {
        return Ok(());
    }
    if visited.contains(&dictionary.to_bits()) {
        return Ok(());
    }
    visited.push(dictionary.to_bits());

    let Some(count) = count_if_collection(env, dictionary) else {
        return Ok(());
    };
    let Some(all_keys_selector) = env.objc.lookup_selector("allKeys") else {
        return Ok(());
    };
    let Some(object_for_key_selector) = env.objc.lookup_selector("objectForKey:") else {
        return Ok(());
    };
    if !debug_object_has_method(env, dictionary, all_keys_selector)
        || !debug_object_has_method(env, dictionary, object_for_key_selector)
    {
        return Ok(());
    }

    let keys: id = msg_send_no_type_checking(env, (dictionary, all_keys_selector));
    let indent = "  ".repeat(depth);
    writeln!(
        writer,
        "{indent}dictionary entries showing {}/{}:",
        count.min(24),
        count
    )?;
    dump_dictionary_common_fields(env, writer, dictionary, depth + 1)?;
    for idx in 0..count.min(24) {
        let Some(key) = object_at_index_if_collection(env, keys, idx) else {
            continue;
        };
        let value: id = msg_send_no_type_checking(env, (dictionary, object_for_key_selector, key));
        writeln!(
            writer,
            "{indent}  [{}] {} => {}",
            idx,
            object_context_debug_value(env, key),
            object_context_debug_value(env, value)
        )?;

        if value == nil
            || visited.contains(&value.to_bits())
            || debug_object_class(env, value).is_none()
            || object_scalar_debug_value(env, value).is_some()
            || !should_recurse_market_context_object(env, value)
        {
            continue;
        }
        if object_is_ns_dictionary(env, value) {
            dump_market_dictionary_entries(
                env,
                writer,
                value,
                depth + 2,
                remaining.saturating_sub(1),
                visited,
            )?;
        } else {
            if remaining == 0 {
                continue;
            }
            dump_market_collection_entries(env, writer, value, depth + 2, remaining - 1, visited)?;
            dump_market_context_ivars(env, writer, value, depth + 2, remaining - 1, visited)?;
        }
    }

    Ok(())
}

fn dump_invocation_debug(
    env: &mut Environment,
    writer: &mut dyn Write,
    invocation: id,
    depth: usize,
) -> IoResult<()> {
    let Some(info) =
        crate::frameworks::foundation::ns_invocation::debug_invocation_info(env, invocation)
    else {
        return Ok(());
    };
    let indent = "  ".repeat(depth);
    let selector = info.selector_name.as_deref().unwrap_or("<unset>");
    writeln!(
        writer,
        "{indent}target={} selector={selector}",
        object_to_debug(env, info.target)
    )?;
    if depth <= 5
        && info.target != nil
        && class_name_looks_market_context(&debug_class_name(env, info.target))
    {
        let mut visited = vec![invocation.to_bits()];
        dump_market_context_ivars(env, writer, info.target, depth + 1, 3, &mut visited)?;
    }
    for argument in info.arguments {
        let value = match argument.value {
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::Object(
                object,
            )) => {
                if let Some(text) = object_string_value_including_empty(env, object) {
                    format!("{:?} ({})", text, object_to_debug(env, object))
                } else {
                    object_to_debug(env, object)
                }
            }
            Some(
                crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::Selector(
                    selector,
                ),
            ) => selector.as_str(&env.mem).to_string(),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::F32(
                value,
            )) => format!("{value:.3}"),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::F64(
                value,
            )) => format!("{value:.3}"),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::I32(
                value,
            )) => value.to_string(),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::U32(
                value,
            )) => value.to_string(),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::I64(
                value,
            )) => value.to_string(),
            Some(crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::U64(
                value,
            )) => value.to_string(),
            Some(
                crate::frameworks::foundation::ns_invocation::DebugInvocationArgumentValue::Pointer(
                    value,
                ),
            ) => format!("0x{value:x}"),
            None => "<unset>".to_string(),
        };
        writeln!(
            writer,
            "{indent}arg[{}] type={} value={value}",
            argument.index, argument.type_
        )?;
    }
    Ok(())
}

fn dump_nearby_cocos_text_inner(
    env: &mut Environment,
    writer: &mut dyn Write,
    node: id,
    search_rect: CGRect,
    depth: usize,
    tree_depth: usize,
    visited: &mut Vec<u32>,
    found: &mut usize,
) -> IoResult<()> {
    if node == nil || debug_object_class(env, node).is_none() || tree_depth > 14 || *found >= 80 {
        return Ok(());
    }

    let node_bits = node.to_bits();
    if visited.contains(&node_bits) {
        return Ok(());
    }
    visited.push(node_bits);

    let visible = node_bool_by_getter(env, node, "isVisible")
        .or_else(|| node_bool_by_getter(env, node, "visible"))
        .unwrap_or(true);
    let class_name = debug_class_name(env, node).to_string();
    let world_rect = node_size_by_getter(env, node, "contentSize")
        .filter(|size| size.width > 0.0 && size.height > 0.0)
        .and_then(|size| node_world_rect(env, node, size));
    let origin = node_world_origin(env, node);
    let is_near = world_rect.is_some_and(|rect| rects_intersect(rect, search_rect))
        || origin.is_some_and(|point| point_in_rect(point, search_rect));

    if visible && is_near && class_name_looks_text_related(&class_name) {
        *found += 1;
        let indent = "  ".repeat(depth);
        let rect = world_rect
            .map(rect_to_debug)
            .unwrap_or_else(|| "n/a".to_string());
        writeln!(
            writer,
            "{indent}[{}] 0x{:x} {} world_rect={} {}",
            *found,
            node_bits,
            class_name,
            rect,
            cocos_node_summary(env, node)
        )?;
        let mut text_visited = Vec::new();
        dump_cocos_text_scan(env, writer, node, depth + 1, 2, &mut text_visited)?;
    }

    if let Some((children, count)) = node_children(env, node) {
        for idx in 0..count.min(256) {
            let Some(child) = object_at_index_if_collection(env, children, idx) else {
                continue;
            };
            dump_nearby_cocos_text_inner(
                env,
                writer,
                child,
                search_rect,
                depth,
                tree_depth + 1,
                visited,
                found,
            )?;
        }
    }

    Ok(())
}

fn class_name_looks_text_related(class_name: &str) -> bool {
    [
        "Label",
        "Text",
        "Font",
        "BMFont",
        "BitmapFont",
        "MenuItem",
        "String",
        "Title",
        "Price",
        "Cost",
    ]
    .iter()
    .any(|needle| class_name.contains(needle))
}

fn class_name_looks_market_context(class_name: &str) -> bool {
    [
        "Market", "Shop", "Store", "Offer", "Product", "Item", "Crop", "Seed", "Plant", "Zombie",
        "MenuItem", "Buyable",
    ]
    .iter()
    .any(|needle| class_name.contains(needle))
}

fn ivar_name_looks_text_related(ivar_name: &str) -> bool {
    let name = ivar_name.to_ascii_lowercase();
    ["string", "text", "label", "font", "title", "name"]
        .iter()
        .any(|needle| name.contains(needle))
}

fn ivar_name_looks_market_context(class_name: &str, ivar_name: &str) -> bool {
    if ivar_name_is_primary_market_context(ivar_name) {
        return true;
    }

    let name = ivar_name.to_ascii_lowercase();
    let broad_market_item = class_name.contains("MenuItem") || class_name.contains("Buyable");
    broad_market_item
        || [
            "item", "market", "offer", "product", "crop", "seed", "plant", "zombie", "price",
            "cost", "name", "key", "desc", "label", "sprite", "image", "icon", "data", "dict",
            "array", "list", "category", "type", "id",
        ]
        .iter()
        .any(|needle| name.contains(needle))
}

fn ivar_name_is_primary_market_context(ivar_name: &str) -> bool {
    matches!(
        ivar_name,
        "itemLayer"
            | "label_"
            | "normalImage_"
            | "selectedImage_"
            | "disabledImage_"
            | "subItems_"
            | "userData"
            | "invocation"
            | "block_"
            | "key"
    )
}

fn should_skip_market_context_ivar(ivar_name: &str) -> bool {
    matches!(
        ivar_name,
        "parent_"
            | "children_"
            | "camera_"
            | "grid_"
            | "transform_"
            | "transformGL_"
            | "inverse_"
            | "contentSize_"
            | "anchorPoint_"
            | "anchorPointInPixels_"
            | "position_"
            | "rotation_"
            | "scaleX_"
            | "scaleY_"
            | "zOrder_"
            | "vertexZ_"
            | "visible_"
            | "isRunning_"
            | "isSelected_"
            | "isEnabled_"
            | "isTransformDirty_"
            | "isTransformGLDirty_"
            | "isInverseDirty_"
            | "isRelativeAnchorPoint_"
            | "tag_"
    )
}

fn should_recurse_market_context_object(env: &Environment, object: id) -> bool {
    let class_name = debug_class_name(env, object);
    class_name_looks_market_context(&class_name)
        || class_name_looks_text_related(&class_name)
        || class_name.contains("Sprite")
        || class_name.contains("Layer")
        || class_name.contains("Dictionary")
        || class_name.contains("Array")
}

fn expand_rect(rect: CGRect, amount: f32) -> CGRect {
    let x = rect.origin.x - amount;
    let y = rect.origin.y - amount;
    let width = rect.size.width + amount * 2.0;
    let height = rect.size.height + amount * 2.0;
    CGRect {
        origin: CGPoint { x, y },
        size: CGSize { width, height },
    }
}

fn rects_intersect(a: CGRect, b: CGRect) -> bool {
    let a_min_x = a.origin.x;
    let a_min_y = a.origin.y;
    let a_max_x = a.origin.x + a.size.width;
    let a_max_y = a.origin.y + a.size.height;
    let b_min_x = b.origin.x;
    let b_min_y = b.origin.y;
    let b_max_x = b.origin.x + b.size.width;
    let b_max_y = b.origin.y + b.size.height;
    a_min_x <= b_max_x && a_max_x >= b_min_x && a_min_y <= b_max_y && a_max_y >= b_min_y
}

fn point_in_rect(point: CGPoint, rect: CGRect) -> bool {
    let min_x = rect.origin.x;
    let min_y = rect.origin.y;
    let max_x = rect.origin.x + rect.size.width;
    let max_y = rect.origin.y + rect.size.height;
    point.x >= min_x && point.x <= max_x && point.y >= min_y && point.y <= max_y
}

fn rect_to_debug(rect: CGRect) -> String {
    let x = rect.origin.x;
    let y = rect.origin.y;
    let width = rect.size.width;
    let height = rect.size.height;
    format!("{{x={x:.1}, y={y:.1}, w={width:.1}, h={height:.1}}}")
}

fn cocos_node_summary(env: &mut Environment, node: id) -> String {
    let position = node_point_by_getter(env, node, "position")
        .map(|point| point.to_string())
        .unwrap_or_else(|| "n/a".to_string());
    let world = node_world_origin(env, node)
        .map(|point| point.to_string())
        .unwrap_or_else(|| "n/a".to_string());
    let anchor = node_point_by_getter(env, node, "anchorPoint")
        .map(|point| point.to_string())
        .unwrap_or_else(|| "n/a".to_string());
    let size = node_size_by_getter(env, node, "contentSize")
        .map(|size| size.to_string())
        .unwrap_or_else(|| "n/a".to_string());
    let scale_x = node_f32_by_getter(env, node, "scaleX")
        .map(|scale| format!("{scale:.3}"))
        .unwrap_or_else(|| "n/a".to_string());
    let scale_y = node_f32_by_getter(env, node, "scaleY")
        .map(|scale| format!("{scale:.3}"))
        .unwrap_or_else(|| "n/a".to_string());
    let rotation = node_f32_by_getter(env, node, "rotation")
        .map(|rotation| format!("{rotation:.3}"))
        .unwrap_or_else(|| "n/a".to_string());
    let visible = node_bool_by_getter(env, node, "isVisible")
        .or_else(|| node_bool_by_getter(env, node, "visible"))
        .map(|visible| visible.to_string())
        .unwrap_or_else(|| "n/a".to_string());

    format!(
        "pos={position} world0={world} anchor={anchor} size={size} scale=({scale_x},{scale_y}) rot={rotation} visible={visible}"
    )
}

fn dump_optional_ivar(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    let Some(value) = read_object_ivar(env, object, ivar_name) else {
        return Ok(());
    };
    writeln!(
        writer,
        "{indent}.{ivar_name} = {}",
        object_to_debug_with_count(env, value)
    )
}

fn dump_optional_string_ivar(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    let Some(value) = read_object_ivar(env, object, ivar_name) else {
        return Ok(());
    };
    writeln!(
        writer,
        "{indent}.{ivar_name} = {}",
        string_object_to_debug(env, value)
    )
}

fn dump_optional_point_ivar(
    env: &Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    if debug_object_class(env, object).is_none() {
        return Ok(());
    }
    let Some(ivar) = env
        .objc
        .object_lookup_ivar(&env.mem, object, &ivar_name.to_string())
    else {
        return Ok(());
    };
    let value: CGPoint = env.mem.read(ivar.cast());
    writeln!(writer, "{indent}.{ivar_name} = {value}")
}

fn dump_optional_size_ivar(
    env: &Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    if debug_object_class(env, object).is_none() {
        return Ok(());
    }
    let Some(ivar) = env
        .objc
        .object_lookup_ivar(&env.mem, object, &ivar_name.to_string())
    else {
        return Ok(());
    };
    let value: CGSize = env.mem.read(ivar.cast());
    writeln!(writer, "{indent}.{ivar_name} = {value}")
}

fn dump_optional_rect_ivar(
    env: &Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    if debug_object_class(env, object).is_none() {
        return Ok(());
    }
    let Some(ivar) = env
        .objc
        .object_lookup_ivar(&env.mem, object, &ivar_name.to_string())
    else {
        return Ok(());
    };
    let value: CGRect = env.mem.read(ivar.cast());
    writeln!(
        writer,
        "{indent}.{ivar_name} = {{{}, {}}}",
        value.origin, value.size
    )
}

fn dump_optional_f32_ivar(
    env: &Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    let Some(value) = read_f32_ivar(env, object, ivar_name) else {
        return Ok(());
    };
    writeln!(writer, "{indent}.{ivar_name} = {value:.3}")
}

fn dump_optional_i32_ivar(
    env: &Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    if debug_object_class(env, object).is_none() {
        return Ok(());
    }
    let Some(ivar) = env
        .objc
        .object_lookup_ivar(&env.mem, object, &ivar_name.to_string())
    else {
        return Ok(());
    };
    let value: i32 = env.mem.read(ivar.cast());
    writeln!(writer, "{indent}.{ivar_name} = {value}")
}

fn dump_attachment_array_ivar(
    env: &mut Environment,
    writer: &mut dyn Write,
    object: id,
    ivar_name: &str,
    depth: usize,
) -> IoResult<()> {
    let indent = "  ".repeat(depth);
    let Some(array) = read_object_ivar(env, object, ivar_name) else {
        return Ok(());
    };
    let Some(count) = count_if_collection(env, array) else {
        return Ok(());
    };
    if count == 0 {
        return Ok(());
    }
    if depth >= 8 {
        writeln!(
            writer,
            "{indent}.{ivar_name} entries omitted at depth {depth} count={count}"
        )?;
        return Ok(());
    }

    writeln!(
        writer,
        "{indent}.{ivar_name} entries showing {}/{}:",
        count.min(32),
        count
    )?;
    for idx in 0..count.min(32) {
        let entry_indent = "  ".repeat(depth + 1);
        let Some(entry) = object_at_index_if_collection(env, array, idx) else {
            continue;
        };
        writeln!(
            writer,
            "{entry_indent}[{idx}] {}",
            object_to_debug_with_count(env, entry)
        )?;
        dump_texture_debug_ivars(env, writer, entry, depth + 2)?;
    }

    Ok(())
}

fn dump_texture_debug_ivars(
    env: &mut Environment,
    writer: &mut dyn Write,
    node: id,
    depth: usize,
) -> IoResult<()> {
    for ivar_name in [
        "spriteMan",
        "attachments",
        "particles",
        "unitDictionary",
        "actorDictionary",
        "spriteDictionary",
        "skeletonDictionary",
        "fightData",
        "farmData",
        "currentAttackVariation",
        "sprite",
        "actor",
        "childAttachments",
        "parentAttachment",
    ] {
        dump_optional_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in ["spriteFileName", "spriteFrameFile", "actionString", "image"] {
        dump_optional_string_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in [
        "originalAnchor",
        "offsetFromRefPoint",
        "lastFramePosition",
        "frameOffset",
        "destinationPoint",
        "currentTile",
        "destinationTile",
        "myHomeTile",
        "rootTile",
        "actorSpecificOffset",
        "collisionBoxOffset",
        "knockBackPoint",
        "throwOffset",
        "lifeBarOffset",
    ] {
        dump_optional_point_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in ["collisionBoxSize"] {
        dump_optional_size_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in ["atlasRect", "rect"] {
        dump_optional_rect_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in [
        "lastFrameRotation",
        "changeInRotation",
        "lastFrameScale",
        "originalRotation",
        "rotation",
        "scale",
        "scaleX",
        "scaleY",
        "walkingSpeed",
        "animSpeed",
        "hitPoints",
        "hitPointsTotal",
    ] {
        dump_optional_f32_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in [
        "attachmentID",
        "tagID",
        "attachmentZOrder",
        "currentTileX",
        "currentTileY",
        "destinationTileX",
        "destinationTileY",
        "myHomeTileX",
        "myHomeTileY",
        "type",
        "subType",
        "flags",
    ] {
        dump_optional_i32_ivar(env, writer, node, ivar_name, depth)?;
    }
    for ivar_name in ["attachments", "childAttachments"] {
        dump_attachment_array_ivar(env, writer, node, ivar_name, depth)?;
    }
    Ok(())
}

fn dump_cocos_node(
    env: &mut Environment,
    writer: &mut dyn Write,
    node: id,
    depth: usize,
    visited: &mut Vec<u32>,
) -> IoResult<()> {
    if node == nil {
        return Ok(());
    }
    if debug_object_class(env, node).is_none() {
        return Ok(());
    }
    let node_bits = node.to_bits();
    let indent = "  ".repeat(depth);
    if visited.contains(&node_bits) {
        writeln!(writer, "{indent}0x{node_bits:x} <cycle>")?;
        return Ok(());
    }
    visited.push(node_bits);

    let children_selector = env.objc.lookup_selector("children");
    let children = children_selector.and_then(|selector| {
        env.objc
            .object_has_method(&env.mem, node, selector)
            .then(|| msg_send_no_type_checking(env, (node, selector)))
    });
    let child_count = children.and_then(|children| count_if_collection(env, children));
    let node_summary = cocos_node_summary(env, node);
    writeln!(
        writer,
        "{indent}0x{node_bits:x} {} children={} {node_summary}",
        debug_class_name(env, node),
        child_count
            .map(|count| count.to_string())
            .unwrap_or_else(|| "n/a".to_string())
    )?;

    dump_texture_debug_ivars(env, writer, node, depth + 1)?;

    if depth >= 10 {
        return Ok(());
    }
    let Some(children) = children else {
        return Ok(());
    };
    let Some(count) = child_count else {
        return Ok(());
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return Ok(());
    };
    if !env
        .objc
        .object_has_method(&env.mem, children, object_at_index_selector)
    {
        return Ok(());
    }
    for idx in 0..count.min(80) {
        let child: id = msg_send_no_type_checking(env, (children, object_at_index_selector, idx));
        dump_cocos_node(env, writer, child, depth + 1, visited)?;
    }
    Ok(())
}

fn dump_cocos_scene(env: &mut Environment, writer: &mut dyn Write) -> IoResult<()> {
    writeln!(writer, "== Cocos Scene Inspector ==")?;
    let Some(scene) = get_running_scene(env) else {
        writeln!(writer, "(no running scene)")?;
        return Ok(());
    };
    let mut visited = Vec::new();
    dump_cocos_node(env, writer, scene, 0, &mut visited)
}

fn get_actor_list_from_actor_manager(env: &mut Environment) -> Option<id> {
    let actor_manager_class = env.objc.get_known_class("ZFActorManager", &mut env.mem);
    let actor_manager_selector = env.objc.lookup_selector("actorManager")?;
    if !env
        .objc
        .object_has_method(&env.mem, actor_manager_class, actor_manager_selector)
    {
        return None;
    }
    let actor_manager: id =
        msg_send_no_type_checking(env, (actor_manager_class, actor_manager_selector));
    if actor_manager == nil {
        return None;
    }

    let actor_list_selector = env.objc.lookup_selector("actorList")?;
    if !env
        .objc
        .object_has_method(&env.mem, actor_manager, actor_list_selector)
    {
        return None;
    }
    let actor_list: id = msg_send_no_type_checking(env, (actor_manager, actor_list_selector));
    (actor_list != nil).then_some(actor_list)
}

fn date_property_by_getter(env: &mut Environment, object: id, selector_name: &str) -> Option<id> {
    let selector = env.objc.lookup_selector(selector_name)?;
    (object != nil && env.objc.object_has_method(&env.mem, object, selector))
        .then(|| msg_send_no_type_checking(env, (object, selector)))
}

fn dump_game_time_state(env: &mut Environment, writer: &mut dyn Write) -> IoResult<()> {
    writeln!(writer, "Time state:")?;

    let date_class = env.objc.get_known_class("NSDate", &mut env.mem);
    let now = env.objc.lookup_selector("date").and_then(|selector| {
        env.objc
            .object_has_method(&env.mem, date_class, selector)
            .then(|| msg_send_no_type_checking(env, (date_class, selector)))
    });
    writeln!(
        writer,
        "  NSDate date: {}",
        now.map(|date| date_to_debug(env, date))
            .unwrap_or_else(|| "n/a".to_string())
    )?;

    let game_data = get_game_data(env);
    let game_state = get_game_state(env);
    let gui_layer = get_gui_layer(env);
    writeln!(
        writer,
        "  TOUCHHLE_FAKE_UNIX_TIME: {}",
        std::env::var("TOUCHHLE_FAKE_UNIX_TIME").unwrap_or_else(|_| "unset".to_string())
    )?;
    writeln!(
        writer,
        "  TOUCHHLE_TIME_OFFSET_SECONDS: {}",
        std::env::var("TOUCHHLE_TIME_OFFSET_SECONDS").unwrap_or_else(|_| "unset".to_string())
    )?;
    writeln!(
        writer,
        "  GameState: {}",
        game_state
            .map(|object| object_to_debug(env, object))
            .unwrap_or_else(|| "n/a".to_string())
    )?;
    if let Some(game_state) = game_state {
        let getter_save_date = date_property_by_getter(env, game_state, "saveDate");
        let ivar_save_date = read_object_ivar(env, game_state, "saveDate");
        writeln!(
            writer,
            "  GameState.saveDate(getter): {}",
            getter_save_date
                .map(|date| date_to_debug(env, date))
                .unwrap_or_else(|| "n/a".to_string())
        )?;
        writeln!(
            writer,
            "  GameState.saveDate(ivar): {}",
            ivar_save_date
                .map(|date| date_to_debug(env, date))
                .unwrap_or_else(|| "n/a".to_string())
        )?;
    }
    writeln!(
        writer,
        "  ZFGuiLayer.gui: {}",
        gui_layer
            .map(|object| object_to_debug(env, object))
            .unwrap_or_else(|| "n/a".to_string())
    )?;
    if let Some(gui_layer) = gui_layer {
        let server_date = read_object_ivar(env, gui_layer, "serverDate");
        writeln!(
            writer,
            "  ZFGuiLayer.serverDate(ivar): {}",
            server_date
                .map(|date| date_to_debug(env, date))
                .unwrap_or_else(|| "n/a".to_string())
        )?;
    }
    writeln!(
        writer,
        "  GameData: {}",
        game_data
            .map(|object| object_to_debug(env, object))
            .unwrap_or_else(|| "n/a".to_string())
    )?;
    if let Some(game_data) = game_data {
        let getter_save_date = date_property_by_getter(env, game_data, "saveDate");
        let ivar_save_date = read_object_ivar(env, game_data, "saveDate");
        writeln!(
            writer,
            "  GameData.saveDate(getter): {}",
            getter_save_date
                .map(|date| date_to_debug(env, date))
                .unwrap_or_else(|| "n/a".to_string())
        )?;
        writeln!(
            writer,
            "  GameData.saveDate(ivar): {}",
            ivar_save_date
                .map(|date| date_to_debug(env, date))
                .unwrap_or_else(|| "n/a".to_string())
        )?;
    }

    let save_path = env.fs.home_directory().join("Documents/saveGame.bin2");
    let save_size = env
        .fs
        .size(GuestPath::new(save_path.as_str()))
        .map(|size| size.to_string())
        .unwrap_or_else(|_| "missing".to_string());
    writeln!(writer, "  saveGame.bin2 size: {save_size}")?;

    Ok(())
}

fn dump_actor_list(
    env: &mut Environment,
    writer: &mut dyn Write,
    title: &str,
    actor_list: Option<id>,
) -> IoResult<()> {
    writeln!(writer, "{title}")?;
    let Some(actor_list) = actor_list else {
        writeln!(writer, "  (not available)")?;
        return Ok(());
    };

    let Some(count_selector) = env.objc.lookup_selector("count") else {
        writeln!(writer, "  (NSArray count selector missing)")?;
        return Ok(());
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        writeln!(writer, "  (NSArray objectAtIndex: selector missing)")?;
        return Ok(());
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        writeln!(
            writer,
            "  0x{:x} {} is not NSArray-like",
            actor_list.to_bits(),
            debug_class_name(env, actor_list)
        )?;
        return Ok(());
    }

    let hunger_selector = env.objc.lookup_selector("hunger");
    let hunger_level_selector = env.objc.lookup_selector("hungerLevel");
    let eat_date_selector = env.objc.lookup_selector("eatDate");
    let time_interval_since_date_selector = env.objc.lookup_selector("timeIntervalSinceDate:");
    let date_class = env.objc.get_known_class("NSDate", &mut env.mem);
    let date_selector = env.objc.lookup_selector("date");
    let now = if let Some(date_selector) = date_selector {
        if env
            .objc
            .object_has_method(&env.mem, date_class, date_selector)
        {
            msg_send_no_type_checking(env, (date_class, date_selector))
        } else {
            nil
        }
    } else {
        nil
    };

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    writeln!(
        writer,
        "  list=0x{:x} {} count={count}",
        actor_list.to_bits(),
        debug_class_name(env, actor_list)
    )?;

    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        let class_name = debug_class_name(env, actor);
        let getter_hunger = hunger_selector.and_then(|selector| {
            (actor != nil && env.objc.object_has_method(&env.mem, actor, selector))
                .then(|| msg_send_no_type_checking::<f32, _>(env, (actor, selector)))
        });
        let ivar_hunger = (actor != nil)
            .then(|| read_f32_ivar(env, actor, "hunger"))
            .flatten();
        let hunger_level = hunger_level_selector.and_then(|selector| {
            (actor != nil && env.objc.object_has_method(&env.mem, actor, selector))
                .then(|| msg_send_no_type_checking::<u32, _>(env, (actor, selector)))
        });
        let getter_eat_date = eat_date_selector.and_then(|selector| {
            (actor != nil && env.objc.object_has_method(&env.mem, actor, selector))
                .then(|| msg_send_no_type_checking::<id, _>(env, (actor, selector)))
        });
        let ivar_eat_date = (actor != nil)
            .then(|| read_object_ivar(env, actor, "eatDate"))
            .flatten();
        let eat_date = getter_eat_date.or(ivar_eat_date);
        let elapsed = match (now, eat_date, time_interval_since_date_selector) {
            (now, Some(eat_date), Some(selector))
                if now != nil
                    && eat_date != nil
                    && env.objc.object_has_method(&env.mem, now, selector) =>
            {
                Some(msg_send_no_type_checking::<f64, _>(
                    env,
                    (now, selector, eat_date),
                ))
            }
            _ => None,
        };

        writeln!(
            writer,
            "  [{idx:02}] 0x{:x} {:<32} hunger(getter)={} hunger(ivar)={} hungerLevel={} eatDate(getter)={} eatDate(ivar)={} elapsed={}s",
            actor.to_bits(),
            class_name,
            getter_hunger
                .map(|value| format!("{value:.3}"))
                .unwrap_or_else(|| "n/a".to_string()),
            ivar_hunger
                .map(|value| format!("{value:.3}"))
                .unwrap_or_else(|| "n/a".to_string()),
            hunger_level
                .map(|value| format!("{value} (0x{value:x}, f32={:.3})", f32::from_bits(value)))
                .unwrap_or_else(|| "n/a".to_string()),
            getter_eat_date
                .map(|value| date_to_debug(env, value))
                .unwrap_or_else(|| "n/a".to_string()),
            ivar_eat_date
                .map(|value| date_to_debug(env, value))
                .unwrap_or_else(|| "n/a".to_string()),
            elapsed
                .map(|value| format!("{value:.0}"))
                .unwrap_or_else(|| "n/a".to_string()),
        )?;
    }

    Ok(())
}

fn get_label_string(env: &mut Environment, label: id) -> String {
    if label == nil {
        return "nil".to_string();
    }

    for selector_name in ["string", "text"] {
        if let Some(selector) = env.objc.lookup_selector(selector_name) {
            if env.objc.object_has_method(&env.mem, label, selector) {
                let value: id = msg_send_no_type_checking(env, (label, selector));
                return format!("{selector_name}={}", string_object_to_debug(env, value));
            }
        }
    }

    if let Some(value) = read_object_ivar(env, label, "string") {
        return format!("ivar string={}", string_object_to_debug(env, value));
    }
    if let Some(value) = read_object_ivar(env, label, "label") {
        return format!("ivar label={}", object_to_debug(env, value));
    }

    "(no string/text found)".to_string()
}

fn dump_actor_summary(env: &mut Environment, writer: &mut dyn Write, actor: id) -> IoResult<()> {
    writeln!(writer, "  actor={}", object_to_debug(env, actor))?;
    if actor == nil {
        return Ok(());
    }

    if let Some(hunger) = read_f32_ivar(env, actor, "hunger") {
        writeln!(writer, "    ivar hunger={hunger:.3}")?;
    } else {
        writeln!(writer, "    ivar hunger=n/a")?;
    }

    if let Some(selector) = env.objc.lookup_selector("hunger") {
        if env.objc.object_has_method(&env.mem, actor, selector) {
            let hunger: f32 = msg_send_no_type_checking(env, (actor, selector));
            writeln!(writer, "    getter hunger={hunger:.3}")?;
        } else {
            writeln!(writer, "    getter hunger=n/a")?;
        }
    }
    if let Some(selector) = env.objc.lookup_selector("hungerLevel") {
        if env.objc.object_has_method(&env.mem, actor, selector) {
            let value: u32 = msg_send_no_type_checking(env, (actor, selector));
            writeln!(
                writer,
                "    getter hungerLevel={value} (0x{value:x}, f32={:.3})",
                f32::from_bits(value)
            )?;
        }
    }

    let eat_date = read_object_ivar(env, actor, "eatDate").or_else(|| {
        let selector = env.objc.lookup_selector("eatDate")?;
        if env.objc.object_has_method(&env.mem, actor, selector) {
            Some(msg_send_no_type_checking(env, (actor, selector)))
        } else {
            None
        }
    });
    if let Some(eat_date) = eat_date {
        writeln!(writer, "    eatDate={}", date_to_debug(env, eat_date))?;

        if let Some(selector) = env.objc.lookup_selector("timeIntervalSinceDate:") {
            let now_class = env.objc.get_known_class("NSDate", &mut env.mem);
            if let Some(date_selector) = env.objc.lookup_selector("date") {
                if env
                    .objc
                    .object_has_method(&env.mem, now_class, date_selector)
                {
                    let now: id = msg_send_no_type_checking(env, (now_class, date_selector));
                    if now != nil
                        && eat_date != nil
                        && env.objc.object_has_method(&env.mem, now, selector)
                    {
                        let elapsed: f64 =
                            msg_send_no_type_checking(env, (now, selector, eat_date));
                        writeln!(writer, "    elapsedSinceEatDate={elapsed:.0}s")?;
                    }
                }
            }
        }
    } else {
        writeln!(writer, "    eatDate=n/a")?;
    }

    Ok(())
}

fn get_zombie_menu(env: &mut Environment) -> Option<id> {
    if env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2" {
        return None;
    }

    let zombie_menu_class = env.objc.get_known_class("ZFZombieMenu", &mut env.mem);
    let zombie_menu_selector = env.objc.lookup_selector("zombieMenu")?;
    if !env
        .objc
        .object_has_method(&env.mem, zombie_menu_class, zombie_menu_selector)
    {
        return None;
    }
    let zombie_menu: id = msg_send_no_type_checking(env, (zombie_menu_class, zombie_menu_selector));
    (zombie_menu != nil).then_some(zombie_menu)
}

fn dump_zombie_menu(env: &mut Environment, writer: &mut dyn Write) -> IoResult<()> {
    writeln!(writer, "ZFZombieMenu:")?;
    let Some(menu) = get_zombie_menu(env) else {
        writeln!(writer, "  (not available)")?;
        return Ok(());
    };
    writeln!(writer, "  menu={}", object_to_debug(env, menu))?;

    let current_zombie_getter = env
        .objc
        .lookup_selector("currentZombie")
        .and_then(|selector| {
            env.objc
                .object_has_method(&env.mem, menu, selector)
                .then(|| msg_send_no_type_checking(env, (menu, selector)))
        });
    let current_zombie_ivar = read_object_ivar(env, menu, "currentZombie");
    writeln!(
        writer,
        "  currentZombie(getter)={}",
        current_zombie_getter
            .map(|object| object_to_debug(env, object))
            .unwrap_or_else(|| "n/a".to_string())
    )?;
    writeln!(
        writer,
        "  currentZombie(ivar)={}",
        current_zombie_ivar
            .map(|object| object_to_debug(env, object))
            .unwrap_or_else(|| "n/a".to_string())
    )?;
    if let Some(current_zombie) = current_zombie_getter.or(current_zombie_ivar) {
        dump_actor_summary(env, writer, current_zombie)?;
    }

    for ivar_name in [
        "nameLabel",
        "statusValLabel",
        "hungerLabel",
        "hungerValLabel",
        "typeValLabel",
        "invasionsValLabel",
    ] {
        let Some(label) = read_object_ivar(env, menu, ivar_name) else {
            writeln!(writer, "  {ivar_name}=n/a")?;
            continue;
        };
        writeln!(
            writer,
            "  {ivar_name}={} {}",
            object_to_debug(env, label),
            get_label_string(env, label)
        )?;
    }

    Ok(())
}

pub fn write_actor_snapshot(env: &mut Environment, mut writer: impl Write) -> IoResult<()> {
    writeln!(writer, "== Zombie Farm Actor Inspector ==")?;
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
    {
        writeln!(writer, "(not a Zombie Farm bundle)")?;
        return Ok(());
    }

    let regs = *env.cpu.regs();
    let result = (|| -> IoResult<()> {
        dump_game_time_state(env, &mut writer)?;
        let game_state_actor_list = get_actor_list_from_game_state(env);
        let actor_manager_actor_list = get_actor_list_from_actor_manager(env);
        dump_actor_list(
            env,
            &mut writer,
            "GameState.zfGameData.actorList:",
            game_state_actor_list,
        )?;
        dump_actor_list(
            env,
            &mut writer,
            "ZFActorManager.actorList:",
            actor_manager_actor_list,
        )?;
        dump_zombie_menu(env, &mut writer)?;
        dump_cocos_scene(env, &mut writer)?;
        Ok(())
    })();
    env.cpu.regs_mut().copy_from_slice(&regs);

    result
}
