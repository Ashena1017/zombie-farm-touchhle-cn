/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Zombie Farm-specific Objective-C message workarounds and tracing helpers.

use super::{autorelease, id, msg_send_no_type_checking, nil, release, retain, ObjC, SEL};
use crate::cpu::Cpu;
use crate::frameworks::core_foundation::time::SECS_FROM_UNIX_TO_APPLE_EPOCHS;
use crate::frameworks::core_graphics::{CGPoint, CGSize};
use crate::frameworks::foundation::{
    ns_date, ns_dictionary, ns_property_list_serialization, ns_string, ns_url_connection,
    NSUInteger,
};
use crate::fs::GuestPath;
use crate::mem::{guest_size_of, ConstPtr, MutPtr, MutVoidPtr};
use crate::Environment;
use crate::{msg, msg_class};
use chrono::{DateTime, Local, LocalResult, NaiveDate, TimeZone, Utc};
use plist::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::io::Cursor;
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Mutex, OnceLock,
};

pub(super) fn trace_zombie_farm_daily_message(selector_name: &str) -> bool {
    matches!(
        selector_name,
        "checkDailyEvent"
            | "displayAlertDailyBonus"
            | "displayAlertBrainSpinner"
            | "showDailyEvents"
            | "showDailyBonusRewardInterface"
            | "showChanceSpinInterface"
            | "inputDailyBonusReward:alert:"
            | "incrementDailyBonusRewardDay"
            | "applyReward"
            | "spin"
            | "displayResult"
            | "didWin"
    )
}

pub(super) fn trace_zombie_farm_status_message(class_name: &str, selector_name: &str) -> bool {
    let lower_class = class_name.to_ascii_lowercase();
    let interesting_class = matches!(
        class_name,
        "ZFGuiLayer"
            | "ZFActorManager"
            | "GameState"
            | "GameData"
            | "PlayerProfile"
            | "PlayerProfileManager"
            | "ActiveProfileStatus"
            | "ZFQuestNotification"
    );
    let statusish_class = lower_class.contains("status")
        || lower_class.contains("profile")
        || lower_class.contains("notification");
    let daily_selector = trace_zombie_farm_daily_message(selector_name);
    let interesting_selector = daily_selector
        || matches!(
            selector_name,
            "getServerTime"
                | "handleTimeResponse:"
                | "handleResponse:forAction:"
                | "applyZombieHunger"
                | "statusCheckDone"
                | "startUpChecksComplete"
                | "fixZombieHunger"
                | "makeAllZombiesHungry"
                | "makeAllZombiesFull"
                | "saveGame"
                | "setSaveDate:"
                | "saveDate"
                | "getBeginningOfTheDayFromDate:"
                | "getActivePlayer"
                | "latestStatus"
                | "status"
                | "notification"
                | "notifications"
                | "clear"
                | "clearStatus"
                | "clearForPlayer:"
                | "loadGame"
                | "setGameData:"
                | "setZfGameData:"
                | "zfGameData"
        );
    let statusish_selector = selector_name.eq_ignore_ascii_case("init")
        || selector_name.eq_ignore_ascii_case("dealloc")
        || selector_name.contains("Status")
        || selector_name.contains("status")
        || selector_name.contains("Profile")
        || selector_name.contains("profile")
        || selector_name.contains("Notification")
        || selector_name.contains("notification");
    daily_selector
        || (interesting_class && interesting_selector)
        || (statusish_class && statusish_selector)
}

pub(super) fn trace_zombie_farm_quest_message(class_name: &str, selector_name: &str) -> bool {
    let lower_class = class_name.to_ascii_lowercase();

    let interesting_class = lower_class.contains("quest")
        || lower_class.contains("mission")
        || lower_class.contains("task")
        || lower_class.contains("objective")
        || lower_class.contains("journal");
    let interesting_selector = matches!(
        selector_name,
        "reset"
            | "enable:"
            | "saveGame"
            | "loadGame"
            | "init"
            | "dealloc"
            | "questMan"
            | "questArray"
            | "questQueue"
            | "questPressed:"
            | "openMenuWithQuest:"
            | "displayQuestTable"
            | "setQuest:"
            | "setQuestID:"
            | "quest"
            | "questID"
    );

    interesting_class && interesting_selector
}

pub(super) fn trace_zombie_farm_layout_message(class_name: &str, selector_name: &str) -> bool {
    let table_delegate_selector = matches!(
        selector_name,
        "table:cellAtIndex:" | "numberOfCellsInTable:" | "cellClassForTable:"
    );
    let interesting_class = table_delegate_selector
        || class_name.contains("TableView")
        || class_name == "CCScrollView"
        || class_name.ends_with("Cell");
    let interesting_selector = matches!(
        selector_name,
        "setContentSize:"
            | "setViewSize:"
            | "setContentOffset:"
            | "setDirection:"
            | "direction"
            | "contentSize"
            | "viewSize"
            | "contentOffset"
            | "cellSize"
            | "_setIndex:forCell:"
            | "_indexFromOffset:"
            | "_offsetFromIndex:"
            | "dequeueCell"
            | "_addCellIfNecessary:"
            | "_moveCellOutOfSight:"
            | "_evictCell"
            | "cellWithIndex:"
            | "table:cellAtIndex:"
            | "numberOfCellsInTable:"
            | "cellClassForTable:"
            | "scrollViewDidScroll:"
    );
    interesting_class && interesting_selector
}

pub(super) fn trace_zombie_farm_layout_to_console(selector_name: &str) -> bool {
    !matches!(
        selector_name,
        "setContentSize:"
            | "setViewSize:"
            | "setContentOffset:"
            | "direction"
            | "contentSize"
            | "viewSize"
            | "contentOffset"
            | "cellSize"
            | "_setIndex:forCell:"
            | "_indexFromOffset:"
            | "_offsetFromIndex:"
            | "dequeueCell"
            | "_addCellIfNecessary:"
            | "_moveCellOutOfSight:"
            | "_evictCell"
            | "cellWithIndex:"
            | "table:cellAtIndex:"
            | "numberOfCellsInTable:"
            | "cellClassForTable:"
            | "scrollViewDidScroll:"
    )
}

fn zombie_farm_sprite_trace_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF_SPRITE_TRACE").ok().as_deref() == Some("1"))
}

pub(super) fn zombie_farm_quest_trace_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF_QUEST_TRACE").ok().as_deref() == Some("1"))
}

pub(super) fn zombie_farm_status_trace_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF_STATUS_TRACE").ok().as_deref() == Some("1"))
}

pub(super) fn zombie_farm_daily_trace_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF_DAILY_TRACE").ok().as_deref() == Some("1"))
}

fn zombie_farm_touch_trace_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("TOUCHHLE_ZF2_TOUCH_TRACE").ok().as_deref() == Some("1"))
}

const ZOMBIE_FARM_NO_INVASION_COOLDOWN_ENV: &str = "TOUCHHLE_ZOMBIE_FARM_NO_INVASION_COOLDOWN";
const ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS: f64 = 7_201.0;
static ZOMBIE_FARM_LAST_INVASION_DATE: AtomicUsize = AtomicUsize::new(0);

fn zombie_farm_env_flag_enabled(value: Option<&str>) -> bool {
    value.is_some_and(|value| {
        let value = value.trim();
        value == "1"
            || value.eq_ignore_ascii_case("true")
            || value.eq_ignore_ascii_case("yes")
            || value.eq_ignore_ascii_case("on")
    })
}

fn zombie_farm_no_invasion_cooldown_enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| {
        zombie_farm_env_flag_enabled(
            std::env::var(ZOMBIE_FARM_NO_INVASION_COOLDOWN_ENV)
                .ok()
                .as_deref(),
        )
    })
}

fn zombie_farm_invasion_interval_override(
    enabled: bool,
    selector_name: &str,
    receiver_is_last_invasion_date: bool,
    argument_is_last_invasion_date: bool,
) -> Option<f64> {
    if !enabled {
        return None;
    }

    match selector_name {
        "timeIntervalSinceNow" if receiver_is_last_invasion_date => {
            Some(-ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS)
        }
        "timeIntervalSinceDate:" if argument_is_last_invasion_date => {
            Some(ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS)
        }
        _ => None,
    }
}

fn trace_zombie_farm_sprite_message(env: &Environment, receiver: id, selector_name: &str) {
    if !zombie_farm_sprite_trace_enabled() || !zombie_farm_uses_playforge_bundle(env) {
        return;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver) else {
        return;
    };
    let interesting_class = class_name.starts_with("SpecialStageActor")
        || class_name == "StageActor"
        || class_name == "ActorAttachment"
        || class_name == "CCSprite"
        || class_name == "CCSpriteSheet";
    if !interesting_class {
        return;
    }

    let details = match selector_name {
        "setPosition:" | "setAnchorPoint:" => {
            format!(" {}", point_arg_from_regs(env.cpu.regs(), 2))
        }
        "setScale:" | "setScaleX:" | "setScaleY:" | "setRotation:" => {
            format!(" {:.3}", f32::from_bits(env.cpu.regs()[2]))
        }
        "setVisible:" => format!(" {}", env.cpu.regs()[2] != 0),
        "setTextureRect:" => format!(" origin {}", point_arg_from_regs(env.cpu.regs(), 2)),
        _ => {
            if !matches!(
                selector_name,
                "setTextureRect:rotated:untrimmedSize:" | "setDisplayFrame:" | "setTexture:"
            ) {
                return;
            }
            String::new()
        }
    };

    log!(
        "ZombieFarm sprite trace: [{} {}] receiver {:?}{}",
        class_name,
        selector_name,
        receiver,
        details
    );
}

fn point_arg_from_regs(regs: &[u32], start: usize) -> CGPoint {
    CGPoint {
        x: f32::from_bits(regs[start]),
        y: f32::from_bits(regs[start + 1]),
    }
}

fn size_arg_from_regs(regs: &[u32], start: usize) -> CGSize {
    CGSize {
        width: f32::from_bits(regs[start]),
        height: f32::from_bits(regs[start + 1]),
    }
}

pub(super) fn zombie_farm_layout_arg_details(selector_name: &str, regs: &[u32]) -> Option<String> {
    match selector_name {
        "setContentSize:" | "setViewSize:" => {
            Some(format!("arg size={}", size_arg_from_regs(regs, 2)))
        }
        "setPosition:" | "setContentOffset:" => {
            Some(format!("arg point={}", point_arg_from_regs(regs, 2)))
        }
        "setDirection:" => Some(format!("arg value={}", regs[2])),
        "_offsetFromIndex:" => Some(format!("arg index={}", regs[3])),
        "cellWithIndex:" => Some(format!("arg index={}", regs[2])),
        "_addCellIfNecessary:" | "_moveCellOutOfSight:" => {
            Some(format!("arg cell={:?}", id::from_bits(regs[2])))
        }
        "table:cellAtIndex:" => Some(format!(
            "arg table={:?} index={}",
            id::from_bits(regs[2]),
            regs[3]
        )),
        "numberOfCellsInTable:" | "cellClassForTable:" => {
            Some(format!("arg table={:?}", id::from_bits(regs[2])))
        }
        "_indexFromOffset:" => Some(format!("arg point={}", point_arg_from_regs(regs, 2))),
        "scrollViewDidScroll:" => Some(format!("arg object={:?}", id::from_bits(regs[2]))),
        "setCellLayer:" | "setCellLayer2:" | "setCellActor:" => {
            Some(format!("arg object={:?}", id::from_bits(regs[2])))
        }
        "setCellID:" | "setCurrentCellIndex:" => Some(format!("arg value={}", regs[2])),
        _ => None,
    }
}

pub(super) fn zombie_farm_status_arg_details(selector_name: &str, regs: &[u32]) -> Option<String> {
    match selector_name {
        "setHunger:" => Some(format!("arg hunger={:.3}", f32::from_bits(regs[2]))),
        "setEatDate:"
        | "setSaveDate:"
        | "handleTimeResponse:"
        | "setDailyBonusRewardDisplayDate:"
        | "setDailyBonusRewardRedeemedDate:" => {
            Some(format!("arg object={:?}", id::from_bits(regs[2])))
        }
        "createLabelWithDay:" | "goldAmountForDayCount:" | "brainChanceForDayCount:" => {
            Some(format!("arg day={}", regs[2]))
        }
        "setDailyBonusRewardDayCount:" => Some(format!("arg count={}", regs[2])),
        "inputDailyBonusReward:alert:" => Some(format!(
            "arg reward={:?} alert={:?}",
            id::from_bits(regs[2]),
            id::from_bits(regs[3])
        )),
        "timeIntervalSinceDate:" | "getBeginningOfTheDayFromDate:" => {
            Some(format!("arg date={:?}", id::from_bits(regs[2])))
        }
        "addTimeInterval:" => {
            let mut bytes = [0u8; 8];
            bytes[0..4].copy_from_slice(&regs[2].to_le_bytes());
            bytes[4..8].copy_from_slice(&regs[3].to_le_bytes());
            Some(format!(
                "arg seconds={:.3}",
                f64::from_bits(u64::from_le_bytes(bytes))
            ))
        }
        "handleResponse:forAction:" => Some(format!(
            "arg response={:?} action={:?}",
            id::from_bits(regs[2]),
            id::from_bits(regs[3])
        )),
        "setStatus:" | "setLatestStatus:" | "setActivePlayer:" | "setCurrentPlayer:"
        | "setPlayerProfile:" | "setNotification:" | "setNotifications:" | "setGameData:"
        | "setZfGameData:" => Some(format!("arg object={:?}", id::from_bits(regs[2]))),
        _ => None,
    }
}

pub(super) fn zombie_farm_quest_arg_details(selector_name: &str, regs: &[u32]) -> Option<String> {
    match selector_name {
        "enable:" | "setEnabled:" => Some(format!("arg enabled={}", regs[2] != 0)),
        "setProgress:" | "setValue:" | "setCount:" | "setCurrentCount:" => {
            Some(format!("arg value={}", regs[2]))
        }
        "handleResponse:forAction:" => Some(format!(
            "arg response={:?} action={:?}",
            id::from_bits(regs[2]),
            id::from_bits(regs[3])
        )),
        _ => {
            let arg0 = regs[2];
            let arg1 = regs[3];
            if arg0 == 0 && arg1 == 0 {
                None
            } else {
                Some(format!("arg r2=0x{arg0:x} r3=0x{arg1:x}"))
            }
        }
    }
}

fn zombie_farm_log_quest_getter(env: &mut Environment, quest: id, selector_name: &str) {
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return;
    };
    if !env.objc.object_has_method(&env.mem, quest, selector) {
        return;
    }

    let regs = *env.cpu.regs();
    let value: u32 = msg_send_no_type_checking(env, (quest, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);

    let value_id = id::from_bits(value);
    let value_class = ObjC::read_isa(value_id, &env.mem);
    let string_class = env.objc.get_known_class("NSString", &mut env.mem);
    if value_class != nil && env.objc.class_is_subclass_of(value_class, string_class) {
        log!(
            "ZombieFarm quest state: [{:?} {}] -> {:?} {:?}",
            quest,
            selector_name,
            value_id,
            ns_string::to_rust_string(env, value_id),
        );
    } else {
        let value_class_name = if value_class == nil {
            None
        } else {
            env.objc.try_get_class_name(value_class)
        };
        log!(
            "ZombieFarm quest state: [{:?} {}] -> r0=0x{:x} ({:?}) class {:?}",
            quest,
            selector_name,
            value,
            value_id,
            value_class_name,
        );
    }
}

pub(super) fn zombie_farm_log_quest_object_state(env: &mut Environment, quest: id, context: &str) {
    if !zombie_farm_quest_trace_enabled() || !zombie_farm_object_pointer_looks_valid(env, quest) {
        return;
    }
    let Some(class_name) = zombie_farm_object_class_name(env, quest) else {
        return;
    };

    log!(
        "ZombieFarm quest state: {} object {:?} class {}",
        context,
        quest,
        class_name
    );
    if class_name == "ZFQuestRequirement" {
        zombie_farm_log_quest_getter(env, quest, "description");
        return;
    }
    for selector_name in [
        "questID",
        "quest",
        "questArray",
        "questQueue",
        "notification",
        "requirements",
        "requirement",
        "count",
        "value",
        "currentCount",
        "requiredCount",
        "goalCount",
        "progress",
        "completed",
        "isCompleted",
        "status",
        "title",
        "description",
    ] {
        zombie_farm_log_quest_getter(env, quest, selector_name);
    }
}

fn zombie_farm_log_array_elements_as_quest_objects(
    env: &mut Environment,
    array: id,
    context: &str,
    limit: NSUInteger,
) {
    if !zombie_farm_quest_trace_enabled() || !zombie_farm_object_pointer_looks_valid(env, array) {
        return;
    }
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return;
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return;
    };
    if !env.objc.object_has_method(&env.mem, array, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, array, object_at_index_selector)
    {
        return;
    }

    let regs = *env.cpu.regs();
    let count: NSUInteger = msg_send_no_type_checking(env, (array, count_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);

    for idx in 0..count.min(limit) {
        let regs = *env.cpu.regs();
        let object: id = msg_send_no_type_checking(env, (array, object_at_index_selector, idx));
        env.cpu.regs_mut().copy_from_slice(&regs);
        zombie_farm_log_quest_object_state(env, object, &format!("{}[{}]", context, idx));
    }
}

fn zombie_farm_log_status_getter(env: &mut Environment, object: id, selector_name: &str) {
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return;
    };
    if !env.objc.object_has_method(&env.mem, object, selector) {
        return;
    }

    let regs = *env.cpu.regs();
    let value: u32 = msg_send_no_type_checking(env, (object, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);

    let value_id = id::from_bits(value);
    let value_class = ObjC::read_isa(value_id, &env.mem);
    let string_class = env.objc.get_known_class("NSString", &mut env.mem);
    if value_class != nil && env.objc.class_is_subclass_of(value_class, string_class) {
        log!(
            "ZombieFarm status state: [{:?} {}] -> {:?} {:?}",
            object,
            selector_name,
            value_id,
            ns_string::to_rust_string(env, value_id),
        );
    } else {
        let value_class_name = if value_class == nil {
            None
        } else {
            env.objc.try_get_class_name(value_class)
        };
        log!(
            "ZombieFarm status state: [{:?} {}] -> r0=0x{:x} ({:?}) class {:?}",
            object,
            selector_name,
            value,
            value_id,
            value_class_name,
        );
    }
}

pub(super) fn zombie_farm_log_status_object_state(
    env: &mut Environment,
    object: id,
    context: &str,
) {
    if !zombie_farm_status_trace_enabled() || !zombie_farm_object_pointer_looks_valid(env, object) {
        return;
    }
    let Some(class_name) = zombie_farm_object_class_name(env, object) else {
        return;
    };

    log!(
        "ZombieFarm status state: {} object {:?} class {}",
        context,
        object,
        class_name
    );
    if class_name == "ZFQuestRequirement" {
        zombie_farm_log_status_getter(env, object, "description");
        return;
    }
    for selector_name in [
        "latestStatus",
        "status",
        "notification",
        "notifications",
        "requirements",
        "requirement",
        "count",
        "value",
        "currentCount",
        "requiredCount",
        "goalCount",
        "progress",
        "completed",
        "isCompleted",
        "title",
        "description",
        "profileID",
        "getActivePlayer",
        "activePlayer",
        "currentPlayer",
        "gameData",
        "zfGameData",
        "saveDate",
    ] {
        zombie_farm_log_status_getter(env, object, selector_name);
    }
}

pub(super) fn zombie_farm_uses_playforge_bundle(env: &Environment) -> bool {
    env.bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
}

fn zombie_farm_object_class_name<'a>(env: &'a Environment, object: id) -> Option<&'a str> {
    if !zombie_farm_object_pointer_looks_valid(env, object) {
        return None;
    }
    let class = ObjC::read_isa(object, &env.mem);
    if class == nil {
        return None;
    }
    env.objc.try_get_class_name(class)
}

fn zombie_farm_object_pointer_looks_valid(env: &Environment, object: id) -> bool {
    object != nil && object.to_bits() >= env.mem.null_segment_size() && object.to_bits() % 4 == 0
}

fn zombie_farm_is_exact_legacy_app(env: &Environment) -> bool {
    env.bundle.bundle_identifier() == "com.playforge.ZFR.LZ54D2GT3D"
        && env.bundle.bundle_version() == "1.0"
}

fn zombie_farm_record_last_invasion_date(env: &Environment, receiver: id, selector_name: &str) {
    if !zombie_farm_no_invasion_cooldown_enabled()
        || !zombie_farm_is_exact_legacy_app(env)
        || selector_name != "lastInvasionDate"
        || zombie_farm_object_class_name(env, receiver) != Some("GameData")
    {
        return;
    }

    let date = id::from_bits(env.cpu.regs()[0]);
    let date_bits = if zombie_farm_date_interval(env, date).is_some() {
        date.to_bits() as usize
    } else {
        0
    };
    ZOMBIE_FARM_LAST_INVASION_DATE.store(date_bits, Ordering::Relaxed);
}

fn zombie_farm_override_invasion_cooldown_interval(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_is_exact_legacy_app(env) {
        return false;
    }

    let enabled = zombie_farm_no_invasion_cooldown_enabled();
    let last_invasion_date_bits = ZOMBIE_FARM_LAST_INVASION_DATE.load(Ordering::Relaxed);
    if !enabled || last_invasion_date_bits == 0 {
        return false;
    }

    let receiver_is_last_invasion_date = receiver.to_bits() as usize == last_invasion_date_bits;
    let argument_is_last_invasion_date = selector_name == "timeIntervalSinceDate:"
        && env.cpu.regs()[2] as usize == last_invasion_date_bits;
    let Some(interval) = zombie_farm_invasion_interval_override(
        enabled,
        selector_name,
        receiver_is_last_invasion_date,
        argument_is_last_invasion_date,
    ) else {
        return false;
    };

    let bits = interval.to_bits().to_le_bytes();
    env.cpu.regs_mut()[0] = u32::from_le_bytes(bits[0..4].try_into().unwrap());
    env.cpu.regs_mut()[1] = u32::from_le_bytes(bits[4..8].try_into().unwrap());

    static LOGGED: AtomicBool = AtomicBool::new(false);
    if !LOGGED.swap(true, Ordering::Relaxed) {
        log!(
            "ZombieFarm workaround: {} enabled; invasion cooldown is always ready",
            ZOMBIE_FARM_NO_INVASION_COOLDOWN_ENV
        );
    }
    true
}

fn zombie_farm_sanitize_ccarray_before_cleanup(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !matches!(selector_name, "removeAllObjects" | "dealloc")
        || zombie_farm_object_class_name(env, receiver) != Some("CCArray")
    {
        return false;
    }

    // Zombie Farm's bundled cocos2d uses:
    // struct ccArray { unsigned int num, max; id *arr; };
    let Some(data) = zombie_farm_read_object_ivar(env, receiver, "data") else {
        return false;
    };
    if data == nil {
        return false;
    }

    let data_bits = data.to_bits();
    let data_ptr: ConstPtr<u8> = ConstPtr::from_bits(data_bits);
    if env.mem.try_malloc_size(data_ptr.cast()).unwrap_or(0) < 12 {
        log!(
            "ZombieFarm workaround: skipped [{} {}] with untracked ccArray data 0x{:08x}",
            zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
            selector_name,
            data_bits
        );
        return true;
    }

    let num_ptr: MutPtr<u32> = MutPtr::from_bits(data_bits);
    let arr_ptr_ptr: MutPtr<u32> = MutPtr::from_bits(data_bits + 8);
    let num = env.mem.read(num_ptr);
    let max: u32 = env.mem.read(MutPtr::from_bits(data_bits + 4));
    let arr_bits = env.mem.read(arr_ptr_ptr);
    if num == 0 {
        return false;
    }

    let arr_allocation_size = if arr_bits < env.mem.null_segment_size() {
        None
    } else {
        let arr_ptr: ConstPtr<u8> = ConstPtr::from_bits(arr_bits);
        env.mem.try_malloc_size(arr_ptr.cast())
    };

    const MAX_REASONABLE_CCARRAY_COUNT: u32 = 1 << 20;
    if num > max || num > MAX_REASONABLE_CCARRAY_COUNT {
        env.mem.write(num_ptr, 0);
        if arr_allocation_size.is_none() {
            env.mem.write(MutPtr::<u32>::from_bits(data_bits + 4), 0);
            env.mem.write(arr_ptr_ptr, 0);
        }
        log!(
            "ZombieFarm workaround: cleared corrupt CCArray {:?} before {} (num={}, max={}, arr=0x{:08x})",
            receiver,
            selector_name,
            num,
            max,
            arr_bits
        );
        return false;
    }

    let array_size = num.checked_mul(guest_size_of::<id>()).unwrap();
    if !arr_allocation_size.is_some_and(|size| size >= array_size) {
        // Keep the ccArray header itself so its normal dealloc can release it,
        // but prevent it from walking or freeing an untracked object buffer.
        env.mem.write(num_ptr, 0);
        env.mem.write(MutPtr::<u32>::from_bits(data_bits + 4), 0);
        env.mem.write(arr_ptr_ptr, 0);
        log!(
            "ZombieFarm workaround: cleared CCArray {:?} with untracked object buffer before {} (num={}, max={}, arr=0x{:08x})",
            receiver,
            selector_name,
            num,
            max,
            arr_bits
        );
        return false;
    }

    let mut invalid_count = 0_u32;
    let mut first_invalid = None;
    for index in 0..num {
        let element_ptr: MutPtr<u32> = MutPtr::from_bits(arr_bits + index * guest_size_of::<id>());
        let element_bits = env.mem.read(element_ptr);
        if element_bits == 0 {
            continue;
        }
        let element: id = MutPtr::from_bits(element_bits);
        if env.objc.get_host_object(element).is_none() {
            env.mem.write(element_ptr, 0);
            invalid_count += 1;
            first_invalid.get_or_insert((index, element_bits));
        }
    }

    if let Some((first_index, first_value)) = first_invalid {
        log!(
            "ZombieFarm workaround: removed {} invalid object pointer(s) from CCArray {:?} before {} (num={}, max={}, first index={} value=0x{:08x})",
            invalid_count,
            receiver,
            selector_name,
            num,
            max,
            first_index,
            first_value
        );
    }

    false
}

const ZOMBIE_FARM_CCACTION_HASH_ELEMENT_SIZE: u32 = 52;
const ZOMBIE_FARM_CCACTION_ACTIONS_OFFSET: u32 = 0;
const ZOMBIE_FARM_CCACTION_TARGET_OFFSET: u32 = 4;
const ZOMBIE_FARM_CCACTION_PAUSED_OFFSET: u32 = 17;
const ZOMBIE_FARM_CCACTION_HASH_TABLE_OFFSET: u32 = 20;
const ZOMBIE_FARM_CCACTION_NEXT_OFFSET: u32 = 28;
const ZOMBIE_FARM_CCACTION_MAX_TARGETS: usize = 4096;

fn zombie_farm_is_ccaction_manager_workaround_call(
    exact_legacy_app: bool,
    class_name: Option<&str>,
    selector_name: &str,
) -> bool {
    exact_legacy_app
        && class_name == Some("CCActionManager")
        && matches!(selector_name, "update:" | "resumeTarget:")
}

fn zombie_farm_repair_ccaction_manager_targets(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_is_ccaction_manager_workaround_call(
        zombie_farm_is_exact_legacy_app(env),
        zombie_farm_object_class_name(env, receiver),
        selector_name,
    ) {
        return false;
    }

    let Some(targets_ivar) =
        env.objc
            .object_lookup_ivar(&env.mem, receiver, &"targets".to_string())
    else {
        return false;
    };
    let targets_bits: u32 = env.mem.read(targets_ivar.cast());
    if targets_bits == 0 {
        return false;
    }

    // Zombie Farm's bundled cocos2d uses:
    // struct hashElement {
    //     ccArray *actions; id target; unsigned int actionIndex; id currentAction;
    //     bool currentActionSalvaged; bool paused; UT_hash_handle hh;
    // };
    //
    // Some invasion action callbacks leave an element linked after clearing
    // actions, and can also leave hh.tbl null. CCActionManager::update then
    // dereferences actions unconditionally, while resumeTarget hashes through
    // hh.tbl unconditionally. Keep the linked targets and repair only those
    // two invalid fields so the normal cocos2d cleanup/update flow can proceed.
    let mut node_bits = targets_bits;
    let mut visited = HashSet::new();
    let mut repaired_actions = 0_u32;
    let mut resumed_target = false;
    let requested_target = (selector_name == "resumeTarget:").then(|| env.cpu.regs()[2]);
    let mut head_hash_table_bits = None;

    while node_bits != 0
        && visited.len() < ZOMBIE_FARM_CCACTION_MAX_TARGETS
        && visited.insert(node_bits)
    {
        if node_bits < env.mem.null_segment_size()
            || env
                .mem
                .try_malloc_size(ConstPtr::<u8>::from_bits(node_bits).cast())
                .unwrap_or(0)
                < ZOMBIE_FARM_CCACTION_HASH_ELEMENT_SIZE
        {
            log!(
                "ZombieFarm workaround: stopped CCActionManager target repair at invalid hash element 0x{:08x}",
                node_bits
            );
            break;
        }

        let actions_ptr: MutPtr<u32> =
            MutPtr::from_bits(node_bits + ZOMBIE_FARM_CCACTION_ACTIONS_OFFSET);
        let actions_bits = env.mem.read(actions_ptr);
        let actions_are_valid = actions_bits >= env.mem.null_segment_size()
            && env
                .mem
                .try_malloc_size(ConstPtr::<u8>::from_bits(actions_bits).cast())
                .unwrap_or(0)
                >= 12;
        if !actions_are_valid {
            // ccArray is a plain C allocation: { num, max, arr }. calloc gives
            // cocos2d a valid empty header which its own ccArrayFree can own.
            let replacement = env.mem.calloc(12);
            env.mem.write(actions_ptr, replacement.to_bits());
            repaired_actions += 1;
            log!(
                "ZombieFarm workaround: replaced invalid CCActionManager actions 0x{:08x} with empty ccArray {:?} for hash element 0x{:08x}",
                actions_bits,
                replacement,
                node_bits
            );
        }

        if node_bits == targets_bits {
            head_hash_table_bits = Some(env.mem.read(MutPtr::<u32>::from_bits(
                node_bits + ZOMBIE_FARM_CCACTION_HASH_TABLE_OFFSET,
            )));
        }

        if requested_target.is_some_and(|target| {
            env.mem.read(MutPtr::<u32>::from_bits(
                node_bits + ZOMBIE_FARM_CCACTION_TARGET_OFFSET,
            )) == target
        }) {
            env.mem.write(
                MutPtr::<u8>::from_bits(node_bits + ZOMBIE_FARM_CCACTION_PAUSED_OFFSET),
                0,
            );
            resumed_target = true;
        }

        node_bits = env.mem.read(MutPtr::<u32>::from_bits(
            node_bits + ZOMBIE_FARM_CCACTION_NEXT_OFFSET,
        ));
    }

    if visited.len() == ZOMBIE_FARM_CCACTION_MAX_TARGETS && node_bits != 0 {
        log!(
            "ZombieFarm workaround: stopped CCActionManager target repair after {} elements",
            ZOMBIE_FARM_CCACTION_MAX_TARGETS
        );
    }

    if repaired_actions != 0 {
        log!(
            "ZombieFarm workaround: repaired {} invalid CCActionManager action array(s) before {}",
            repaired_actions,
            selector_name
        );
    }

    if selector_name == "resumeTarget:" && head_hash_table_bits == Some(0) {
        log!(
            "ZombieFarm workaround: handled resumeTarget: through linked targets because uthash table is null (target=0x{:08x}, found={})",
            requested_target.unwrap(),
            resumed_target
        );
        env.cpu.regs_mut()[0..2].fill(0);
        return true;
    }

    false
}

fn zombie_farm_ccarray_storage_is_safe_for_visit(env: &mut Environment, array: id) -> bool {
    if zombie_farm_object_class_name(env, array) != Some("CCArray")
        || env.objc.get_host_object(array).is_none()
    {
        return false;
    }

    let Some(data) = zombie_farm_read_object_ivar(env, array, "data") else {
        return false;
    };
    if data == nil
        || env
            .mem
            .try_malloc_size(data.cast_const().cast())
            .unwrap_or(0)
            < 12
    {
        return false;
    }

    // Zombie Farm's bundled cocos2d uses:
    // struct ccArray { unsigned int num, max; id *arr; };
    let data_bits = data.to_bits();
    let num: u32 = env.mem.read(ConstPtr::from_bits(data_bits));
    let max: u32 = env.mem.read(ConstPtr::from_bits(data_bits + 4));
    let arr_bits: u32 = env.mem.read(ConstPtr::from_bits(data_bits + 8));
    if num == 0 {
        return true;
    }
    if num > max || num > (1 << 20) || arr_bits < env.mem.null_segment_size() {
        return false;
    }

    let required_size = num.checked_mul(guest_size_of::<id>()).unwrap();
    env.mem
        .try_malloc_size(ConstPtr::<u8>::from_bits(arr_bits).cast())
        .is_some_and(|size| size >= required_size)
}

fn zombie_farm_repair_ccnode_children_before_visit(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) {
    if !zombie_farm_is_exact_legacy_app(env) || selector_name != "visit" {
        return;
    }

    let Some(children_ivar) =
        env.objc
            .object_lookup_ivar(&env.mem, receiver, &"children_".to_string())
    else {
        return;
    };
    let children: id = env.mem.read(children_ivar.cast());
    if children == nil || zombie_farm_ccarray_storage_is_safe_for_visit(env, children) {
        return;
    }

    // CCNode's visit implementation dereferences children_->data directly.
    // If the old CCArray has already been deallocated, replace the stale
    // container with a valid empty one and let the node continue its own draw.
    let regs = *env.cpu.regs();
    let replacement: id = msg_class![env; CCArray alloc];
    let capacity: NSUInteger = 1;
    let replacement: id = msg![env; replacement initWithCapacity:capacity];
    if replacement == nil {
        env.cpu.regs_mut().copy_from_slice(&regs);
        return;
    }

    env.mem.write(children_ivar.cast(), replacement);
    env.cpu.regs_mut().copy_from_slice(&regs);
    log!(
        "ZombieFarm workaround: replaced stale CCNode children {:?} on {:?} ({}) before visit",
        children,
        receiver,
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown")
    );
}

pub(super) fn zombie_farm_return_nil_for_stale_object_message(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
    stale_kind: &str,
) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }

    log_dbg!(
        "ZombieFarm workaround: returning nil for [{} {:?} {}]",
        stale_kind,
        receiver,
        selector_name
    );
    env.cpu.regs_mut()[0..2].fill(0);
    true
}

fn zombie_farm_set_gui_layer_server_date_to_now(env: &mut Environment, receiver: id) -> bool {
    if !zombie_farm_uses_playforge_bundle(env)
        || zombie_farm_object_class_name(env, receiver) != Some("ZFGuiLayer")
    {
        return false;
    }

    let ivar_name = "serverDate".to_string();
    let Some(server_date_ivar) = env.objc.object_lookup_ivar(&env.mem, receiver, &ivar_name) else {
        return false;
    };

    let old_server_date: id = env.mem.read(server_date_ivar.cast());
    let now: id = msg_class![env; NSDate date];
    let now = retain(env, now);
    env.mem.write(server_date_ivar.cast(), now);
    if old_server_date != nil && old_server_date != now {
        release(env, old_server_date);
    }
    log!(
        "ZombieFarm status: using local NSDate {:?} as ZFGuiLayer.serverDate",
        now
    );
    true
}

static ZOMBIE_FARM_APPLIED_LOCAL_HUNGER: AtomicBool = AtomicBool::new(false);
static ZOMBIE_FARM_CHECKED_LOCAL_DAILY_EVENT: AtomicBool = AtomicBool::new(false);
pub(super) static ZOMBIE_FARM_APPLY_TRACE_DEPTH: AtomicUsize = AtomicUsize::new(0);
static ZOMBIE_FARM_LAST_MAIN_MENU: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Default)]
struct ZombieFarmCocosTouchHandlers {
    targeted: Vec<u32>,
    standard: Vec<u32>,
    claimed_targeted: HashMap<u32, Vec<u32>>,
}

static ZOMBIE_FARM_COCOS_TOUCH_HANDLERS: OnceLock<
    Mutex<HashMap<u32, ZombieFarmCocosTouchHandlers>>,
> = OnceLock::new();

fn zombie_farm_cocos_touch_handlers() -> &'static Mutex<HashMap<u32, ZombieFarmCocosTouchHandlers>>
{
    ZOMBIE_FARM_COCOS_TOUCH_HANDLERS.get_or_init(|| Mutex::new(HashMap::new()))
}

#[derive(Clone, Copy, Default)]
struct ZombieFarmSyncOperationInfo {
    manager: u32,
    delegate: u32,
}

static ZOMBIE_FARM_SYNC_OPERATIONS: OnceLock<Mutex<HashMap<u32, ZombieFarmSyncOperationInfo>>> =
    OnceLock::new();

fn zombie_farm_sync_operations() -> &'static Mutex<HashMap<u32, ZombieFarmSyncOperationInfo>> {
    ZOMBIE_FARM_SYNC_OPERATIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

#[derive(Default)]
struct ZombieFarmZombieCellState {
    current_assignments: Vec<(u32, u32)>,
    last_zombie_by_cell: HashMap<u32, u32>,
    last_zombie_key_by_cell: HashMap<u32, String>,
}

static ZOMBIE_FARM_ZOMBIE_CELL_STATE: OnceLock<Mutex<ZombieFarmZombieCellState>> = OnceLock::new();
static ZOMBIE_FARM_SELECTOR_DUMPS: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();

fn zombie_farm_zombie_cell_state() -> &'static Mutex<ZombieFarmZombieCellState> {
    ZOMBIE_FARM_ZOMBIE_CELL_STATE.get_or_init(|| Mutex::new(ZombieFarmZombieCellState::default()))
}

fn zombie_farm_selector_dumps() -> &'static Mutex<HashSet<String>> {
    ZOMBIE_FARM_SELECTOR_DUMPS.get_or_init(|| Mutex::new(HashSet::new()))
}

fn zombie_farm_find_cell_zombie_actor(env: &mut Environment, cell: id) -> Option<id> {
    ["cellActor", "actor", "zombieActor"]
        .into_iter()
        .find_map(|selector_name| zombie_farm_get_id_if_responds(env, cell, selector_name))
        .or_else(|| {
            ["node", "cellLayer", "cellLayer2"]
                .into_iter()
                .find_map(|selector_name| zombie_farm_get_id_if_responds(env, cell, selector_name))
                .and_then(|container| {
                    let children = zombie_farm_read_object_ivar(env, container, "children_")
                        .or_else(|| zombie_farm_get_id_if_responds(env, container, "children"))?;
                    let count = zombie_farm_get_array_count(env, children)?;
                    (0..count).find_map(|idx| {
                        let child = zombie_farm_get_array_object_at_index(env, children, idx)?;
                        zombie_farm_actor_is_zombie(env, child).then_some(child)
                    })
                })
        })
}

fn zombie_farm_should_dump_selectors_for_class(class_name: &str) -> bool {
    let lower = class_name.to_ascii_lowercase();
    class_name.starts_with("ZombieActor")
        || class_name == "ActorAttachment"
        || zombie_farm_is_zombie_cell_class_name(class_name)
        || lower.contains("attachment")
}

fn zombie_farm_log_class_selectors_once(env: &Environment, object: id, reason: &str) {
    if !zombie_farm_object_pointer_looks_valid(env, object) {
        return;
    }
    let class = ObjC::read_isa(object, &env.mem);
    if class == nil {
        return;
    }
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return;
    };
    if !zombie_farm_should_dump_selectors_for_class(class_name) {
        return;
    }

    let dump_key = format!("{class_name}::{reason}");
    {
        let mut dumped = zombie_farm_selector_dumps().lock().unwrap();
        if !dumped.insert(dump_key) {
            return;
        }
    }

    let mut selectors = env
        .objc
        .debug_all_class_selectors_as_strings(&env.mem, class);
    selectors.sort();
    selectors.dedup();

    let interesting_keywords = [
        "attach", "sprite", "frame", "anim", "update", "layout", "refresh", "display", "offset",
        "point", "position", "scale", "rotation", "cell", "zombie",
    ];
    let interesting: Vec<_> = selectors
        .iter()
        .filter(|selector| {
            let lower = selector.to_ascii_lowercase();
            interesting_keywords
                .iter()
                .any(|keyword| lower.contains(keyword))
        })
        .cloned()
        .collect();

    log!(
        "ZombieFarm selector dump [{}] class={} object={:?} selector_count={} interesting={}",
        reason,
        class_name,
        object,
        selectors.len(),
        if interesting.is_empty() {
            "<none>".to_string()
        } else {
            interesting.join(" ")
        }
    );
    for chunk in selectors.chunks(24) {
        log!(
            "ZombieFarm selector dump [{}] class={} selectors {}",
            reason,
            class_name,
            chunk.join(" ")
        );
    }
}

fn zombie_farm_is_zombie_cell_class_name(class_name: &str) -> bool {
    class_name == "ZFZombieCell" || class_name.ends_with("ZombieCell")
}

pub(super) fn zombie_farm_begin_zombie_cell_assignment(
    env: &Environment,
    receiver: id,
    selector_name: &str,
    regs: &[u32; 16],
) -> bool {
    if selector_name != "setZombie:" || receiver == nil {
        return false;
    }
    let class = ObjC::read_isa(receiver, &env.mem);
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    let class_name = class_name.to_string();
    if !zombie_farm_is_zombie_cell_class_name(&class_name) {
        return false;
    }
    zombie_farm_zombie_cell_state()
        .lock()
        .unwrap()
        .current_assignments
        .push((receiver.to_bits(), regs[2]));
    true
}

pub(super) fn zombie_farm_finish_zombie_cell_assignment(
    env: &mut Environment,
    started: bool,
    receiver: id,
) {
    if !started || receiver == nil {
        return;
    }
    let assignment = {
        let mut state = zombie_farm_zombie_cell_state().lock().unwrap();
        state.current_assignments.pop()
    };
    let Some((cell_bits, zombie_bits)) = assignment else {
        return;
    };
    if cell_bits != receiver.to_bits() {
        return;
    }
    let zombie_key = zombie_farm_zombie_identity_key(env, id::from_bits(zombie_bits));
    let mut state = zombie_farm_zombie_cell_state().lock().unwrap();
    if zombie_bits == 0 {
        state.last_zombie_by_cell.remove(&cell_bits);
        state.last_zombie_key_by_cell.remove(&cell_bits);
    } else {
        state.last_zombie_by_cell.insert(cell_bits, zombie_bits);
        if let Some(zombie_key) = zombie_key {
            state.last_zombie_key_by_cell.insert(cell_bits, zombie_key);
        } else {
            state.last_zombie_key_by_cell.remove(&cell_bits);
        }
    }
}

fn zombie_farm_clear_zombie_cell_assignment(receiver: id) {
    if receiver == nil {
        return;
    }
    let mut state = zombie_farm_zombie_cell_state().lock().unwrap();
    let cell_bits = receiver.to_bits();
    state.last_zombie_by_cell.remove(&cell_bits);
    state.last_zombie_key_by_cell.remove(&cell_bits);
    state
        .current_assignments
        .retain(|&(cell, _)| cell != cell_bits);
}

fn zombie_farm_send_noarg_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if receiver == nil {
        return false;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return false;
    };
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return false;
    }

    let regs = *env.cpu.regs();
    log!(
        "ZombieFarm workaround: sending [{} {}]",
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
        selector_name
    );
    let _: () = msg_send_no_type_checking(env, (receiver, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    true
}

fn zombie_farm_get_id_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> Option<id> {
    if receiver == nil {
        return None;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return None;
    };
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return None;
    }

    let regs = *env.cpu.regs();
    let value: id = msg_send_no_type_checking(env, (receiver, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    (value != nil).then_some(value)
}

fn zombie_farm_send_id_arg_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
    arg: id,
) -> bool {
    if receiver == nil {
        return false;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return false;
    };
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return false;
    }

    let regs = *env.cpu.regs();
    log!(
        "ZombieFarm workaround: sending [{} {}] arg {:?}",
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
        selector_name,
        arg
    );
    let _: () = msg_send_no_type_checking(env, (receiver, selector, arg));
    env.cpu.regs_mut().copy_from_slice(&regs);
    true
}

fn zombie_farm_get_id_arg_result_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
    arg: id,
) -> Option<id> {
    if receiver == nil {
        return None;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return None;
    };
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return None;
    }

    let regs = *env.cpu.regs();
    let value: id = msg_send_no_type_checking(env, (receiver, selector, arg));
    env.cpu.regs_mut().copy_from_slice(&regs);
    (value != nil).then_some(value)
}

fn zombie_farm_get_i32_arg_result_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
    arg: id,
) -> Option<i32> {
    if receiver == nil {
        return None;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return None;
    };
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return None;
    }

    let regs = *env.cpu.regs();
    let value: i32 = msg_send_no_type_checking(env, (receiver, selector, arg));
    env.cpu.regs_mut().copy_from_slice(&regs);
    Some(value)
}

fn zombie_farm_get_array_count(env: &mut Environment, array: id) -> Option<NSUInteger> {
    let Some(selector) = env.objc.lookup_selector("count") else {
        return None;
    };
    if array == nil || !env.objc.object_has_method(&env.mem, array, selector) {
        return None;
    }

    let regs = *env.cpu.regs();
    let count: NSUInteger = msg_send_no_type_checking(env, (array, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    Some(count)
}

fn zombie_farm_get_array_object_at_index(
    env: &mut Environment,
    array: id,
    idx: NSUInteger,
) -> Option<id> {
    let Some(selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return None;
    };
    if array == nil || !env.objc.object_has_method(&env.mem, array, selector) {
        return None;
    }

    let regs = *env.cpu.regs();
    let value: id = msg_send_no_type_checking(env, (array, selector, idx));
    env.cpu.regs_mut().copy_from_slice(&regs);
    (value != nil).then_some(value)
}

fn zombie_farm_get_value_for_key(env: &mut Environment, receiver: id, key: &str) -> Option<id> {
    let key = ns_string::from_rust_string(env, key.to_string());
    zombie_farm_get_id_arg_result_if_responds(env, receiver, "valueForKey:", key)
}

fn zombie_farm_get_property_object(
    env: &mut Environment,
    receiver: id,
    property_name: &str,
) -> Option<id> {
    zombie_farm_get_id_if_responds(env, receiver, property_name)
        .or_else(|| zombie_farm_get_value_for_key(env, receiver, property_name))
}

fn zombie_farm_get_string_property(
    env: &mut Environment,
    receiver: id,
    property_name: &str,
) -> Option<String> {
    let value = zombie_farm_get_property_object(env, receiver, property_name)?;
    Some(ns_string::to_rust_string(env, value).to_string())
}

fn zombie_farm_get_i32_property(
    env: &mut Environment,
    receiver: id,
    property_name: &str,
) -> Option<i32> {
    if let Some(value) = zombie_farm_get_value_for_key(env, receiver, property_name) {
        if let Some(int_value_selector) = env.objc.lookup_selector("intValue") {
            if env
                .objc
                .object_has_method(&env.mem, value, int_value_selector)
            {
                let regs = *env.cpu.regs();
                let int_value: i32 = msg_send_no_type_checking(env, (value, int_value_selector));
                env.cpu.regs_mut().copy_from_slice(&regs);
                return Some(int_value);
            }
        }
    }
    None
}

fn zombie_farm_get_string_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> Option<String> {
    let value = zombie_farm_get_id_if_responds(env, receiver, selector_name)?;
    Some(ns_string::to_rust_string(env, value).to_string())
}

fn zombie_farm_get_u32_if_responds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> Option<u32> {
    if receiver == nil {
        return None;
    }
    let selector = env.objc.lookup_selector(selector_name)?;
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return None;
    }
    let regs = *env.cpu.regs();
    let value: u32 = msg_send_no_type_checking(env, (receiver, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    Some(value)
}

fn zombie_farm_zombie_identity_key(env: &mut Environment, zombie: id) -> Option<String> {
    if zombie == nil {
        return None;
    }
    let class = ObjC::read_isa(zombie, &env.mem);
    let class_name = env.objc.try_get_class_name(class).unwrap_or("unknown");
    let mut parts = vec![class_name.to_string()];

    if let Some(name) = zombie_farm_get_string_if_responds(env, zombie, "name") {
        parts.push(format!("name={name}"));
    }
    if let Some(idx) = zombie_farm_get_u32_if_responds(env, zombie, "idx") {
        parts.push(format!("idx={idx}"));
    }
    if let Some(number) = zombie_farm_get_u32_if_responds(env, zombie, "number") {
        parts.push(format!("number={number}"));
    }
    if let Some(place) = zombie_farm_get_u32_if_responds(env, zombie, "place") {
        parts.push(format!("place={place}"));
    }

    (parts.len() > 1).then(|| parts.join("|"))
}

fn zombie_farm_get_bool_property(
    env: &mut Environment,
    receiver: id,
    property_name: &str,
) -> Option<bool> {
    if receiver == nil {
        return None;
    }
    let selector = env.objc.lookup_selector(property_name)?;
    if !env.objc.object_has_method(&env.mem, receiver, selector) {
        return None;
    }
    let regs = *env.cpu.regs();
    let bool_value: bool = msg_send_no_type_checking(env, (receiver, selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    Some(bool_value)
}

pub fn zombie_farm_complete_all_quests_cheat(env: &mut Environment) {
    if !zombie_farm_uses_playforge_bundle(env) {
        return;
    }

    static ALREADY_RAN: AtomicBool = AtomicBool::new(false);
    if ALREADY_RAN.swap(true, Ordering::Relaxed) {
        log!("ZombieFarm cheat: F9 complete-all-quests already executed for this run.");
        return;
    }

    let Some(quest_man) = zombie_farm_get_quest_man(env) else {
        log!("ZombieFarm cheat: F9 ignored because ZFQuestMan is unavailable.");
        return;
    };
    let Some(quest_queue) = zombie_farm_get_id_if_responds(env, quest_man, "questQueue") else {
        log!("ZombieFarm cheat: F9 ignored because questQueue is unavailable.");
        return;
    };
    let Some(mut quest_count) = zombie_farm_get_array_count(env, quest_queue) else {
        log!("ZombieFarm cheat: F9 ignored because questQueue count is unavailable.");
        return;
    };

    let Some(complete_selector) = env.objc.lookup_selector("completeQuest:") else {
        log!("ZombieFarm cheat: F9 ignored because completeQuest: selector is unavailable.");
        return;
    };
    if !env
        .objc
        .object_has_method(&env.mem, quest_man, complete_selector)
    {
        log!("ZombieFarm cheat: F9 ignored because ZFQuestMan does not respond to completeQuest:.");
        return;
    }

    let mut completed = 0usize;
    let mut skipped = 0usize;
    let mut seen_queue_heads = HashSet::new();

    let mut guard = 0usize;
    while quest_count > 0 && guard < 512 {
        guard += 1;
        let Some(quest_object) = zombie_farm_get_array_object_at_index(env, quest_queue, 0) else {
            skipped += 1;
            break;
        };
        if !seen_queue_heads.insert(quest_object.to_bits()) {
            log!(
                "ZombieFarm cheat: stopping because questQueue head 0x{:x} repeated without advancing.",
                quest_object.to_bits()
            );
            skipped += 1;
            break;
        }

        let already_completed = zombie_farm_get_bool_property(env, quest_object, "completed")
            .or_else(|| zombie_farm_get_bool_property(env, quest_object, "isCompleted"))
            .unwrap_or(false);
        if already_completed {
            skipped += 1;
            break;
        }

        let title = zombie_farm_get_string_property(env, quest_object, "title")
            .or_else(|| {
                zombie_farm_get_property_object(env, quest_object, "quest")
                    .and_then(|quest| zombie_farm_get_string_property(env, quest, "title"))
            })
            .unwrap_or_else(|| "queued quest".to_string());

        let regs = *env.cpu.regs();
        let _: () = msg_send_no_type_checking(env, (quest_man, complete_selector, quest_object));
        env.cpu.regs_mut().copy_from_slice(&regs);
        completed += 1;
        log!(
            "ZombieFarm cheat: completed quest {} via [ZFQuestMan completeQuest:]",
            title
        );

        let _ = zombie_farm_send_noarg_if_responds(env, quest_man, "reorderQuests");
        quest_count = zombie_farm_get_array_count(env, quest_queue).unwrap_or(0);
    }

    let _ = zombie_farm_send_noarg_if_responds(env, quest_man, "reorderQuests");
    let _ = zombie_farm_send_noarg_if_responds(env, quest_man, "updateStats");
    if let Some(gui_layer) = zombie_farm_get_gui_layer(env) {
        let _ = zombie_farm_send_noarg_if_responds(env, gui_layer, "updateStats");
    }

    log!(
        "ZombieFarm cheat: F9 complete-all-quests finished, completed {}, skipped {}",
        completed,
        skipped
    );
}

fn zombie_farm_local_time_response(env: &mut Environment) -> id {
    let now: id = msg_class![env; NSDate date];
    let unix_time: f64 = msg![env; now timeIntervalSince1970];
    let utc_time: id = msg_class![env; NSNumber numberWithDouble:unix_time];
    let utc_time_key = ns_string::from_rust_string(env, "utcTime".to_string());
    let action_key = ns_string::from_rust_string(env, "action".to_string());
    let action = ns_string::from_rust_string(env, "time".to_string());
    let operation_key = ns_string::from_rust_string(env, "operation".to_string());
    let operation_class = env
        .objc
        .get_known_class("BrainClientOperation", &mut env.mem);
    let operation_alloc_selector = env.objc.lookup_selector("alloc").unwrap();
    let allocated_operation: id =
        msg_send_no_type_checking(env, (operation_class, operation_alloc_selector));
    let operation = if let Some(init_selector) = env.objc.lookup_selector("init") {
        if env
            .objc
            .object_has_method(&env.mem, allocated_operation, init_selector)
        {
            msg_send_no_type_checking(env, (allocated_operation, init_selector))
        } else {
            allocated_operation
        }
    } else {
        allocated_operation
    };

    let mut entries = vec![(utc_time_key, utc_time), (action_key, action)];
    entries.push((operation_key, operation));
    ns_dictionary::dict_from_keys_and_objects(env, &entries)
}

pub(super) fn zombie_farm_ignore_spurious_operation_done(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) || selector_name != "operationDone" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        if zombie_farm_object_pointer_looks_valid(env, receiver) {
            let class = ObjC::read_isa(receiver, &env.mem);
            env.cpu.regs_mut()[0] = 0;
            if class == nil {
                log!(
                    "ZombieFarm workaround: ignoring spurious [deallocated {:?} operationDone]",
                    receiver
                );
                return true;
            }
            if env.objc.try_get_class_name(class).is_none() {
                log!(
                    "ZombieFarm workaround: ignoring spurious [stale {:?} operationDone] with unregistered class {:?}",
                    receiver,
                    class
                );
                return true;
            }
        }
        return false;
    };
    if let Some(operation_done_selector) = env.objc.lookup_selector(selector_name) {
        if env
            .objc
            .object_has_method(&env.mem, receiver, operation_done_selector)
        {
            return false;
        }
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm workaround: ignoring spurious [{} operationDone]",
        class_name
    );
    true
}

fn zombie_farm_forward_backing_array_fast_enumeration(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || selector_name != "countByEnumeratingWithState:objects:count:"
    {
        return false;
    }
    let Some(array_selector) = env.objc.lookup_selector("_array") else {
        return false;
    };
    if !env
        .objc
        .object_has_method(&env.mem, receiver, array_selector)
    {
        return false;
    }

    let regs = *env.cpu.regs();
    let backing_array: id = msg_send_no_type_checking(env, (receiver, array_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    if backing_array == nil {
        return false;
    }

    let state = MutVoidPtr::from_bits(regs[2]);
    let objects = MutVoidPtr::from_bits(regs[3]);
    let count: NSUInteger = env.mem.read(ConstPtr::<u32>::from_bits(regs[Cpu::SP]));
    let result: NSUInteger =
        msg_send_no_type_checking(env, (backing_array, selector, state, objects, count));
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[0] = result;
    log_dbg!(
        "ZombieFarm2 workaround: forwarded fast enumeration for {} through backing array {:?}",
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
        backing_array
    );
    true
}

fn zombie_farm_ignore_null_attachment_placeholder(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("NSNull")
        || !matches!(
            selector_name,
            "calculateRotateValue"
                | "calculateBonePosition"
                | "rotateBone:aroundPoint:"
                | "flipBonePosition"
                | "rotateBone:aroundPoint:rotateChildren:"
                | "addBone:"
                | "setRotation:"
                | "setSprite:"
                | "setOriginalAnchor:"
                | "setOffsetFromRefPoint:"
                | "setLastFramePosition:"
                | "setAtlasRect:"
                | "setLastFrameRotation:"
                | "setChangeInRotation:"
                | "setLastFrameScale:"
                | "setInheritColor:"
                | "setCanSwap:"
                | "setChildAttachments:"
                | "setParentAttachment:"
                | "setOriginalRotation:"
                | "setFollowRotation:"
                | "setImage:"
                | "setAttachmentZOrder:"
                | "setFlippedAsset:"
                | "childAttachments"
                | "parentAttachment"
                | "sprite"
                | "image"
                | "originalAnchor"
                | "offsetFromRefPoint"
                | "lastFramePosition"
                | "atlasRect"
                | "lastFrameRotation"
                | "changeInRotation"
                | "lastFrameScale"
                | "inheritColor"
                | "canSwap"
                | "originalRotation"
                | "followRotation"
                | "attachmentZOrder"
                | "flippedAsset"
                | "tag"
                | "setTag:"
                | "parent"
                | "children"
                | "isVisible"
                | "visible"
                | "setVisible:"
                | "opacity"
                | "setOpacity:"
                | "rotation"
                | "scale"
                | "scaleX"
                | "scaleY"
                | "setScale:"
                | "setScaleX:"
                | "setScaleY:"
                | "addChild:"
                | "addChild:z:"
                | "removeFromParent"
                | "removeFromParentAndCleanup:"
                | "stopAllActions"
                | "runAction:"
                | "cleanup"
        )
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    env.cpu.regs_mut()[1] = 0;
    log_dbg!(
        "ZombieFarm2 workaround: ignoring NSNull attachment placeholder [{}]",
        selector_name
    );
    true
}

fn zombie_farm_last_main_menu() -> Option<id> {
    let bits = ZOMBIE_FARM_LAST_MAIN_MENU.load(Ordering::Relaxed) as u32;
    (bits != 0).then_some(id::from_bits(bits))
}

fn zombie_farm_remove_view_controller_view(
    env: &mut Environment,
    controller: id,
    context: &str,
) -> bool {
    if controller == nil {
        return false;
    }
    let Some(view_selector) = env.objc.lookup_selector("view") else {
        return false;
    };
    if !env
        .objc
        .object_has_method(&env.mem, controller, view_selector)
    {
        return false;
    }

    let regs = *env.cpu.regs();
    let view: id = msg_send_no_type_checking(env, (controller, view_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    if view == nil {
        return false;
    }

    let Some(remove_selector) = env.objc.lookup_selector("removeFromSuperview") else {
        return false;
    };
    if !env.objc.object_has_method(&env.mem, view, remove_selector) {
        return false;
    }

    let regs = *env.cpu.regs();
    let _: () = msg_send_no_type_checking(env, (view, remove_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    log!(
        "ZombieFarm2 workaround: removed {} view {:?} from superview",
        context,
        view
    );
    true
}

fn zombie_farm_remove_stale_uikit_subviews_by_class(env: &mut Environment, class_name: &str) {
    let removed = crate::frameworks::uikit::ui_view::remove_subviews_by_class(env, class_name);
    if removed > 0 {
        log!(
            "ZombieFarm2 workaround: removed {} stale {} UIKit view(s)",
            removed,
            class_name
        );
    }
}

fn zombie_farm_reveal_hud_controls(env: &mut Environment, context: &str) {
    let revealed = crate::frameworks::uikit::ui_view::reveal_zombie_farm_hud_controls(env);
    if revealed > 0 {
        log!(
            "ZombieFarm2 workaround: revealed {} hidden HUD/UIKit control(s) after {}",
            revealed,
            context
        );
    }
}

fn zombie_farm_get_gui_layer(env: &mut Environment) -> Option<id> {
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

fn zombie_farm_get_quest_man(env: &mut Environment) -> Option<id> {
    let quest_man_class = env.objc.get_known_class("ZFQuestMan", &mut env.mem);
    let quest_man_selector = env.objc.lookup_selector("questMan")?;
    if !env
        .objc
        .object_has_method(&env.mem, quest_man_class, quest_man_selector)
    {
        return None;
    }
    let quest_man: id = msg_send_no_type_checking(env, (quest_man_class, quest_man_selector));
    (quest_man != nil).then_some(quest_man)
}

fn zombie_farm_get_active_player(env: &mut Environment) -> Option<id> {
    let manager_class = env
        .objc
        .get_known_class("PlayerProfileManager", &mut env.mem);
    let manager_selector = env.objc.lookup_selector("playerProfileManager")?;
    if !env
        .objc
        .object_has_method(&env.mem, manager_class, manager_selector)
    {
        return None;
    }
    let manager: id = msg_send_no_type_checking(env, (manager_class, manager_selector));
    if manager == nil {
        return None;
    }

    for selector_name in ["getActivePlayer", "activePlayer", "currentPlayer"] {
        if let Some(player) = zombie_farm_get_id_if_responds(env, manager, selector_name) {
            return Some(player);
        }
    }
    None
}

fn zombie_farm_log_local_quest_restore_snapshot(
    env: &mut Environment,
    context: &str,
    gui_layer: Option<id>,
    quest_man: Option<id>,
) {
    log!(
        "ZombieFarm workaround: quest restore snapshot ({})",
        context
    );

    if let Some(gui_layer) = gui_layer {
        zombie_farm_log_status_object_state(env, gui_layer, "quest restore guiLayer");
    }

    if let Some(quest_man) = quest_man {
        zombie_farm_log_quest_object_state(env, quest_man, "quest restore questMan");
        if let Some(quest_queue) = zombie_farm_get_id_if_responds(env, quest_man, "questQueue") {
            zombie_farm_log_quest_object_state(env, quest_queue, "quest restore questQueue");
            if zombie_farm_quest_trace_enabled() {
                let count_selector = env.objc.lookup_selector("count");
                let object_at_index_selector = env.objc.lookup_selector("objectAtIndex:");
                if let (Some(count_selector), Some(object_at_index_selector)) =
                    (count_selector, object_at_index_selector)
                {
                    if env
                        .objc
                        .object_has_method(&env.mem, quest_queue, count_selector)
                        && env.objc.object_has_method(
                            &env.mem,
                            quest_queue,
                            object_at_index_selector,
                        )
                    {
                        let regs = *env.cpu.regs();
                        let count: NSUInteger =
                            msg_send_no_type_checking(env, (quest_queue, count_selector));
                        env.cpu.regs_mut().copy_from_slice(&regs);
                        for idx in 0..count.min(16) {
                            let regs = *env.cpu.regs();
                            let quest_notification: id = msg_send_no_type_checking(
                                env,
                                (quest_queue, object_at_index_selector, idx),
                            );
                            env.cpu.regs_mut().copy_from_slice(&regs);
                            if let Some(requirements) = zombie_farm_get_id_if_responds(
                                env,
                                quest_notification,
                                "requirements",
                            ) {
                                zombie_farm_log_array_elements_as_quest_objects(
                                    env,
                                    requirements,
                                    &format!("quest restore questQueue[{}].requirements", idx),
                                    8,
                                );
                            }
                            zombie_farm_log_quest_object_state(
                                env,
                                quest_notification,
                                &format!("quest restore questQueue[{}]", idx),
                            );
                        }
                    }
                }
            }
        }
        if let Some(quest_array) = zombie_farm_get_id_if_responds(env, quest_man, "questArray") {
            zombie_farm_log_quest_object_state(env, quest_array, "quest restore questArray");
        }
    }

    if let Some(active_player) = zombie_farm_get_active_player(env) {
        zombie_farm_log_status_object_state(env, active_player, "quest restore activePlayer");
        if let Some(latest_status) =
            zombie_farm_get_id_if_responds(env, active_player, "latestStatus")
        {
            zombie_farm_log_status_object_state(
                env,
                latest_status,
                "quest restore activePlayer.latestStatus",
            );
        }
        if let Some(status) = zombie_farm_get_id_if_responds(env, active_player, "status") {
            zombie_farm_log_status_object_state(env, status, "quest restore activePlayer.status");
        }
    }
}

fn zombie_farm_get_game_state(env: &mut Environment) -> Option<id> {
    let game_state_class = env.objc.get_known_class("GameState", &mut env.mem);
    let game_state_selector = env.objc.lookup_selector("gameState")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_state_class, game_state_selector)
    {
        return None;
    }
    let game_state: id = msg_send_no_type_checking(env, (game_state_class, game_state_selector));
    (game_state != nil).then_some(game_state)
}

fn zombie_farm_get_running_scene(env: &mut Environment) -> Option<id> {
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

fn zombie_farm_find_cocos_child_by_class(
    env: &mut Environment,
    root: id,
    class_name: &str,
    depth: usize,
) -> Option<id> {
    if root == nil || depth > 8 {
        return None;
    }
    if zombie_farm_object_class_name(env, root) == Some(class_name) {
        return Some(root);
    }

    let children_selector = env.objc.lookup_selector("children")?;
    if !env
        .objc
        .object_has_method(&env.mem, root, children_selector)
    {
        return None;
    }
    let children: id = msg_send_no_type_checking(env, (root, children_selector));
    if children == nil {
        return None;
    }

    let count_selector = env.objc.lookup_selector("count")?;
    let object_at_index_selector = env.objc.lookup_selector("objectAtIndex:")?;
    if !env
        .objc
        .object_has_method(&env.mem, children, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, children, object_at_index_selector)
    {
        return None;
    }
    let count: NSUInteger = msg_send_no_type_checking(env, (children, count_selector));
    for idx in 0..count.min(200) {
        let child: id = msg_send_no_type_checking(env, (children, object_at_index_selector, idx));
        if let Some(found) =
            zombie_farm_find_cocos_child_by_class(env, child, class_name, depth + 1)
        {
            return Some(found);
        }
    }
    None
}

fn zombie_farm_get_farm_tile_map(env: &mut Environment) -> Option<id> {
    let running_scene = zombie_farm_get_running_scene(env)?;
    if let Some(farm_tile_map_selector) = env.objc.lookup_selector("farmTileMap") {
        if env
            .objc
            .object_has_method(&env.mem, running_scene, farm_tile_map_selector)
        {
            let tile_map: id =
                msg_send_no_type_checking(env, (running_scene, farm_tile_map_selector));
            if tile_map != nil {
                return Some(tile_map);
            }
        }
    }
    zombie_farm_find_cocos_child_by_class(env, running_scene, "ZFFarmTileMap", 0)
}

/// Bounds for the wheel's zoom value.
///
/// The value passed to `-setZoomOutAmount:` is used directly as the
/// `CCScaleTo` scale for the map node, so a larger value means a larger map
/// (zoomed in) and 1.0 is the neutral/default level that `-resetCamera` seeds.
///
/// `-setZoomOutAmount:` applies its own clamps, but the lower one is
/// device-dependent and is *negative* on iPad-sized windows (`0.9 -
/// winSize.width * 0.01`), i.e. it never binds. A scale at or below zero would
/// make the farm vanish, so the wheel keeps its own floor at 0.2 - the same
/// floor the game uses on iPhone-sized windows. The ceiling matches the game's
/// own upper clamp on iPad-sized windows; on smaller windows the game clamps
/// further to 1.0 by itself.
const ZOMBIE_FARM_ZOOM_MIN: f32 = 0.2;
const ZOMBIE_FARM_ZOOM_MAX: f32 = 2.0;
/// Zoom level to assume before the game has recorded one.
const ZOMBIE_FARM_ZOOM_DEFAULT: f32 = 1.0;

fn zombie_farm_read_zoom_factor(env: &Environment, tile_map: id) -> Option<f32> {
    let ivar = env
        .objc
        .object_lookup_ivar(&env.mem, tile_map, &"zoomFactor".to_string())?;
    Some(env.mem.read(ivar.cast()))
}

/// Mouse-wheel zoom for the farm map.
///
/// The game only ever changes its zoom through `-[ZFFarmTileMap
/// setZoomOutAmount:]`, which is what its own two-finger pinch handler calls
/// (see `-ccTouchMoved:withEvent:`). Driving that same setter means the tiles,
/// actors, particles and camera all get repositioned by the game's own code, so
/// the wheel behaves exactly like a pinch instead of just scaling the layer.
///
/// A positive `notches` (wheel scrolled away from the user) zooms in, matching
/// the usual map-app convention.
///
/// The per-notch ratio comes from `--zf-wheel-zoom-step=` (see
/// [crate::options::ZF_WHEEL_ZOOM_STEP_DEFAULT]). A constant *ratio* is used
/// rather than a constant increment because the game's own pinch gesture is
/// multiplicative too (`new = distance_ratio * originalScale`, see
/// `-ccTouchMoved:withEvent:`), so a ratio keeps the feel identical at every
/// zoom level.
///
/// Returns true if the zoom actually changed.
pub fn zombie_farm_zoom_step(env: &mut Environment, notches: i32) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }
    let Some(tile_map) = zombie_farm_get_farm_tile_map(env) else {
        log!("ZombieFarm zoom: ignored, farm map is not loaded yet.");
        return false;
    };
    let Some(set_zoom_selector) = env.objc.lookup_selector("setZoomOutAmount:") else {
        log!("ZombieFarm zoom: ignored, setZoomOutAmount: is unavailable.");
        return false;
    };
    if !env
        .objc
        .object_has_method(&env.mem, tile_map, set_zoom_selector)
    {
        log!("ZombieFarm zoom: ignored, farm map does not respond to setZoomOutAmount:.");
        return false;
    }

    // Start from the game's own stored value so the wheel and the pinch gesture
    // never disagree about the current level. A missing or non-positive value
    // means the game has not zoomed yet, so fall back to its default.
    let current = zombie_farm_read_zoom_factor(env, tile_map)
        .filter(|value| *value > 0.0)
        .unwrap_or(ZOMBIE_FARM_ZOOM_DEFAULT);
    // Read once per step: the option is fixed for the process lifetime, but
    // taking it here keeps the value next to the arithmetic it feeds.
    let step = env.options.zf_wheel_zoom_step;
    let target = (current * step.powi(notches))
        .clamp(ZOMBIE_FARM_ZOOM_MIN, ZOMBIE_FARM_ZOOM_MAX);

    if (target - current).abs() < f32::EPSILON {
        log!(
            "ZombieFarm zoom: wheel {:+} notch(es) ignored, already at the {} limit ({:.3}).",
            notches,
            if notches > 0 { "zoomed-in" } else { "zoomed-out" },
            current
        );
        return false;
    }

    let regs = *env.cpu.regs();
    let _: () = msg_send_no_type_checking(env, (tile_map, set_zoom_selector, target));
    env.cpu.regs_mut().copy_from_slice(&regs);

    // The game stores what it actually accepted in the `zoomFactor` ivar, so
    // read it back: it may have clamped us further (e.g. to 1.0 on a
    // iPhone-sized window). It also returns early, storing nothing, if a
    // previous zoom animation is still running (each is 0.01s long), which is
    // indistinguishable from a clamp here and simply means this notch was
    // folded into the animation already in flight.
    let applied = zombie_farm_read_zoom_factor(env, tile_map).unwrap_or(target);
    if (applied - current).abs() < f32::EPSILON {
        log!(
            "ZombieFarm zoom: wheel {:+} notch(es) left the zoom at {:.3} \
             (requested {:.3}; clamped or the previous step is still animating).",
            notches,
            current,
            target
        );
        return false;
    }

    log!(
        "ZombieFarm zoom: wheel {:+} notch(es) -> {:.3} (was {:.3}).",
        notches,
        applied,
        current
    );
    true
}

fn zombie_farm_get_actor_list(env: &mut Environment) -> Option<id> {
    let game_state = zombie_farm_get_game_state(env)?;
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

fn zombie_farm_get_game_data(env: &mut Environment) -> Option<id> {
    let game_state = zombie_farm_get_game_state(env)?;
    let zf_game_data_selector = env.objc.lookup_selector("zfGameData")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_state, zf_game_data_selector)
    {
        return None;
    }
    let game_data: id = msg_send_no_type_checking(env, (game_state, zf_game_data_selector));
    (game_data != nil).then_some(game_data)
}

fn zombie_farm_post_notification_name_object(
    env: &mut Environment,
    name: &str,
    object: id,
) -> bool {
    let center: id = msg_class![env; NSNotificationCenter defaultCenter];
    if center == nil {
        return false;
    }
    let notification_name = ns_string::from_rust_string(env, name.to_string());
    let regs = *env.cpu.regs();
    let _: () = msg![env; center postNotificationName:notification_name object:object];
    env.cpu.regs_mut().copy_from_slice(&regs);
    true
}

fn zombie_farm_parse_assignment_line(line: &str, key: &str) -> Option<String> {
    let trimmed = line.trim();
    let prefix = format!("{key} = ");
    let value = trimmed.strip_prefix(&prefix)?.strip_suffix(';')?;
    Some(value.trim().to_string())
}

fn zombie_farm_collect_loot_item_requirement_names_from_description(
    description: &str,
) -> Vec<String> {
    let mut items = Vec::new();
    let mut in_requirement = false;
    let mut notification_id: Option<String> = None;
    let mut notification_object: Option<String> = None;

    for line in description.lines() {
        let trimmed = line.trim();
        if trimmed == "{" {
            in_requirement = true;
            notification_id = None;
            notification_object = None;
            continue;
        }
        if !in_requirement {
            continue;
        }
        if trimmed == "}," || trimmed == "}" {
            if notification_id.as_deref() == Some("kLootItemWonNotification") {
                if let Some(item_name) = notification_object.take() {
                    if !item_name.is_empty() {
                        items.push(item_name);
                    }
                }
            }
            in_requirement = false;
            notification_id = None;
            notification_object = None;
            continue;
        }

        if let Some(value) = zombie_farm_parse_assignment_line(trimmed, "notificationID") {
            notification_id = Some(value);
        } else if let Some(value) = zombie_farm_parse_assignment_line(trimmed, "notificationObject")
        {
            notification_object = Some(value);
        }
    }

    items
}

fn zombie_farm_storage_key_for_display_name(
    env: &mut Environment,
    display_name: &str,
) -> Option<String> {
    let tile_properties_path = env
        .fs
        .home_directory()
        .join("Documents/remoteAssets_1.0/TileProperties.plist");
    let bytes = env
        .fs
        .read(GuestPath::new(tile_properties_path.as_str()))
        .ok()?;
    let root = Value::from_reader(Cursor::new(bytes)).ok()?;
    let dict = root.as_dictionary()?;

    for (storage_key, value) in dict {
        let Some(entry) = value.as_dictionary() else {
            continue;
        };
        let Some(name) = entry.get("name").and_then(Value::as_string) else {
            continue;
        };
        if name == display_name {
            return Some(storage_key.clone());
        }
    }

    None
}

fn zombie_farm_replay_loot_item_notifications_from_inventory(
    env: &mut Environment,
    quest_man: id,
) -> usize {
    let Some(game_data) = zombie_farm_get_game_data(env) else {
        log!(
            "ZombieFarm workaround: quest inventory replay skipped because GameData is unavailable"
        );
        return 0;
    };

    let Some(quest_array) = zombie_farm_get_id_if_responds(env, quest_man, "questArray") else {
        log!(
            "ZombieFarm workaround: quest inventory replay skipped because questArray is unavailable"
        );
        return 0;
    };

    let Some(quest_count) = zombie_farm_get_array_count(env, quest_array) else {
        return 0;
    };

    let mut replayed = 0usize;
    let mut loot_item_candidates = 0usize;
    let mut replayed_items = HashSet::<String>::new();

    for quest_idx in 0..quest_count {
        let Some(quest_definition) =
            zombie_farm_get_array_object_at_index(env, quest_array, quest_idx)
        else {
            continue;
        };
        let Some(description) =
            zombie_farm_get_string_property(env, quest_definition, "description")
        else {
            continue;
        };

        let item_names =
            zombie_farm_collect_loot_item_requirement_names_from_description(&description);
        if item_names
            .iter()
            .any(|item_name| item_name.contains("Circus Flag"))
        {
            log!(
                "ZombieFarm workaround: quest inventory replay parsed circus loot items from quest {}: {:?}",
                quest_idx,
                item_names
            );
        }

        for item_name in item_names {
            loot_item_candidates += 1;
            if item_name.is_empty() || !replayed_items.insert(item_name.clone()) {
                continue;
            }

            let item_name_ns = ns_string::from_rust_string(env, item_name.clone());
            let owned_count_display_name_raw = zombie_farm_get_i32_arg_result_if_responds(
                env,
                game_data,
                "numberOfItemInStorageWithKey:",
                item_name_ns,
            );
            let storage_key = zombie_farm_storage_key_for_display_name(env, &item_name);
            let owned_count_storage_key_raw = storage_key.as_ref().and_then(|storage_key| {
                let storage_key_ns = ns_string::from_rust_string(env, storage_key.clone());
                zombie_farm_get_i32_arg_result_if_responds(
                    env,
                    game_data,
                    "numberOfItemInStorageWithKey:",
                    storage_key_ns,
                )
            });
            let owned_count_display_name = owned_count_display_name_raw.unwrap_or(0);
            let owned_count_storage_key = owned_count_storage_key_raw.unwrap_or(0);
            let owned_count = owned_count_display_name.max(owned_count_storage_key);

            if item_name.contains("Circus Flag") {
                log!(
                    "ZombieFarm workaround: quest inventory replay item {:?}, storage key {:?}, owned display {:?}, owned key {:?}, effective {}",
                    item_name,
                    storage_key,
                    owned_count_display_name_raw,
                    owned_count_storage_key_raw,
                    owned_count
                );
            }

            if owned_count < 1 {
                continue;
            }

            if zombie_farm_post_notification_name_object(
                env,
                "kLootItemWonNotification",
                item_name_ns,
            ) {
                replayed += 1;
                log!(
                    "ZombieFarm workaround: replayed kLootItemWonNotification for {:?} (owned display={}, owned key={}, storage key {:?})",
                    item_name,
                    owned_count_display_name,
                    owned_count_storage_key,
                    storage_key
                );
            }
        }
    }

    log!(
        "ZombieFarm workaround: quest inventory replay finished with {} replay(s) from {} loot item candidate(s)",
        replayed,
        loot_item_candidates
    );

    replayed
}

fn zombie_farm_get_live_actor_list(env: &mut Environment) -> Option<id> {
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

fn zombie_farm_actor_is_zombie(env: &Environment, actor: id) -> bool {
    zombie_farm_object_class_name(env, actor)
        .is_some_and(|class_name| class_name.starts_with("ZombieActor"))
}

fn zombie_farm_write_actor_hunger_ivar(env: &mut Environment, actor: id, hunger: f32) -> bool {
    let ivar_name = "hunger".to_string();
    let Some(ivar) = env.objc.object_lookup_ivar(&env.mem, actor, &ivar_name) else {
        return false;
    };
    env.mem.write(ivar.cast(), hunger);
    true
}

fn zombie_farm_read_actor_hunger_ivar(env: &Environment, actor: id) -> Option<f32> {
    let ivar_name = "hunger".to_string();
    let ivar = env.objc.object_lookup_ivar(&env.mem, actor, &ivar_name)?;
    Some(env.mem.read(ivar.cast()))
}

fn zombie_farm_read_object_ivar(env: &Environment, object: id, ivar_name: &str) -> Option<id> {
    if !zombie_farm_object_pointer_looks_valid(env, object) {
        return None;
    }
    let ivar_name = ivar_name.to_string();
    let ivar = env.objc.object_lookup_ivar(&env.mem, object, &ivar_name)?;
    Some(env.mem.read(ivar.cast()))
}

fn zombie_farm_date_interval(env: &Environment, date: id) -> Option<f64> {
    if !zombie_farm_object_pointer_looks_valid(env, date) {
        return None;
    }
    ns_date::debug_time_interval(env, date)
}

fn zombie_farm_actor_eat_date(env: &mut Environment, actor: id) -> Option<id> {
    let Some(eat_date_selector) = env.objc.lookup_selector("eatDate") else {
        return zombie_farm_read_object_ivar(env, actor, "eatDate")
            .filter(|date| zombie_farm_date_interval(env, *date).is_some());
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor, eat_date_selector)
    {
        return zombie_farm_read_object_ivar(env, actor, "eatDate")
            .filter(|date| zombie_farm_date_interval(env, *date).is_some());
    }

    let eat_date: id = msg_send_no_type_checking(env, (actor, eat_date_selector));
    if zombie_farm_date_interval(env, eat_date).is_some() {
        Some(eat_date)
    } else {
        zombie_farm_read_object_ivar(env, actor, "eatDate")
            .filter(|date| zombie_farm_date_interval(env, *date).is_some())
    }
}

fn zombie_farm_oldest_zombie_eat_date_in_list(
    env: &mut Environment,
    actor_list: id,
) -> Option<(id, f64)> {
    let count_selector = env.objc.lookup_selector("count")?;
    let object_at_index_selector = env.objc.lookup_selector("objectAtIndex:")?;
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return None;
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut oldest: Option<(id, f64)> = None;
    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }

        let Some(eat_date) = zombie_farm_actor_eat_date(env, actor) else {
            continue;
        };
        let Some(interval) = zombie_farm_date_interval(env, eat_date) else {
            continue;
        };

        if oldest
            .as_ref()
            .is_none_or(|(_, oldest_interval)| interval < *oldest_interval)
        {
            oldest = Some((eat_date, interval));
        }
    }

    oldest
}

fn zombie_farm_oldest_zombie_eat_date(env: &mut Environment) -> Option<(id, f64)> {
    let mut oldest: Option<(id, f64)> = None;
    for actor_list in [
        zombie_farm_get_actor_list(env),
        zombie_farm_get_live_actor_list(env),
    ]
    .into_iter()
    .flatten()
    {
        let Some((eat_date, interval)) =
            zombie_farm_oldest_zombie_eat_date_in_list(env, actor_list)
        else {
            continue;
        };
        if oldest
            .as_ref()
            .is_none_or(|(_, oldest_interval)| interval < *oldest_interval)
        {
            oldest = Some((eat_date, interval));
        }
    }
    oldest
}

fn zombie_farm_game_state_save_date(env: &mut Environment, game_state: id) -> Option<id> {
    if let Some(save_date) = zombie_farm_read_object_ivar(env, game_state, "saveDate")
        .filter(|date| zombie_farm_date_interval(env, *date).is_some())
    {
        return Some(save_date);
    }

    let save_date_selector = env.objc.lookup_selector("saveDate")?;
    if !env
        .objc
        .object_has_method(&env.mem, game_state, save_date_selector)
    {
        return None;
    }
    let save_date: id = msg_send_no_type_checking(env, (game_state, save_date_selector));
    (zombie_farm_date_interval(env, save_date).is_some()).then_some(save_date)
}

fn zombie_farm_set_game_state_save_date(env: &mut Environment, game_state: id, save_date: id) {
    if !zombie_farm_object_pointer_looks_valid(env, save_date) {
        return;
    }

    let regs = *env.cpu.regs();
    let Some(save_date_ivar) =
        env.objc
            .object_lookup_ivar(&env.mem, game_state, &"saveDate".to_string())
    else {
        return;
    };
    let old_save_date: id = env.mem.read(save_date_ivar.cast());
    let retained_save_date = retain(env, save_date);
    env.mem.write(save_date_ivar.cast(), retained_save_date);
    if old_save_date != nil && old_save_date != retained_save_date {
        release(env, old_save_date);
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_ensure_game_state_save_date(env: &mut Environment) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }

    let Some(game_state) = zombie_farm_get_game_state(env) else {
        return false;
    };
    if zombie_farm_game_state_save_date(env, game_state).is_some() {
        return true;
    }

    let Some((save_date, interval)) = zombie_farm_oldest_zombie_eat_date(env) else {
        return false;
    };
    zombie_farm_set_game_state_save_date(env, game_state, save_date);
    log!(
        "ZombieFarm status: restored nil GameState.saveDate from oldest zombie eatDate {:?} ({:.3}s since Apple epoch)",
        save_date,
        interval
    );
    true
}

fn zombie_farm_prepare_game_state_save_date(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) {
    if !zombie_farm_uses_playforge_bundle(env)
        || selector_name != "setSaveDate:"
        || zombie_farm_object_class_name(env, receiver) != Some("GameState")
        || id::from_bits(env.cpu.regs()[2]) != nil
    {
        return;
    }

    let regs = *env.cpu.regs();

    if let Some(existing_save_date) = zombie_farm_game_state_save_date(env, receiver) {
        env.cpu.regs_mut().copy_from_slice(&regs);
        log_dbg!(
            "ZombieFarm status: preserving existing GameState.saveDate {:?} for setSaveDate:nil",
            existing_save_date
        );
        return;
    }

    let save_date = if let Some((oldest_eat_date, interval)) =
        zombie_farm_oldest_zombie_eat_date(env)
    {
        log!(
            "ZombieFarm status: replacing GameState setSaveDate:nil with oldest zombie eatDate {:?} ({:.3}s since Apple epoch)",
            oldest_eat_date,
            interval
        );
        oldest_eat_date
    } else {
        let now: id = msg_class![env; NSDate date];
        log!(
            "ZombieFarm status: replacing GameState setSaveDate:nil with local NSDate {:?}",
            now
        );
        now
    };
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[2] = save_date.to_bits();
}

fn zombie_farm_skip_epic_event_with_missing_remote_data(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || selector_name != "validBossID:"
        || zombie_farm_object_class_name(env, receiver) != Some("EpicEventManager")
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: treating EpicEventManager validBossID:{} as false",
        env.cpu.regs()[2]
    );
    true
}

fn zombie_farm_override_cocos2d_get_zeye(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" || selector_name != "getZEye" {
        return false;
    }

    let class = ObjC::read_isa(receiver, &env.mem);
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    if !matches!(
        class_name,
        "CCDirector" | "CCFastDirector" | "CCThreadedFastDirector"
    ) {
        return false;
    }

    let (_, height) = env.window().logical_size();
    let z_eye = height as f32 / 1.1566;
    env.cpu.regs_mut()[0] = z_eye.to_bits();
    log!(
        "ZombieFarm2 workaround: [{} getZEye] -> {:.3}",
        class_name,
        z_eye
    );
    true
}

fn zombie_farm_skip_cocos2d_projection_setup(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || selector_name != "setProjection:"
        || std::env::var("TOUCHHLE_ZF2_SKIP_PROJECTION")
            .ok()
            .as_deref()
            != Some("1")
    {
        return false;
    }

    let class = ObjC::read_isa(receiver, &env.mem);
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    if !matches!(
        class_name,
        "CCDirector" | "CCFastDirector" | "CCThreadedFastDirector"
    ) {
        return false;
    }

    log!(
        "ZombieFarm2 workaround: ignoring [{} setProjection:{}]",
        class_name,
        env.cpu.regs()[2]
    );
    true
}

fn zombie_farm_skip_remote_asset_requests(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || !matches!(
            selector_name,
            "startRemote"
                | "requestManifest"
                | "downloadRemote"
                | "requestAssets"
                | "rerunFailedRequests"
        )
        || zombie_farm_object_class_name(env, receiver) != Some("RemoteManager")
    {
        return false;
    }

    log!(
        "ZombieFarm2 workaround: skipping RemoteManager {}",
        selector_name
    );
    true
}

fn zombie_farm_skip_event_tracker_nil_last_event(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || selector_name != "setLastEvent:"
        || env.cpu.regs()[2] != nil.to_bits()
    {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver) else {
        return false;
    };
    if !matches!(class_name, "EventTracker" | "ZF2EventTracker") {
        return false;
    }

    log!(
        "ZombieFarm2 workaround: ignoring [{} setLastEvent:nil]",
        class_name
    );
    true
}

fn zombie_farm_skip_event_tracker_init(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" || selector_name != "init" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };
    if !matches!(class_name.as_str(), "EventTracker" | "ZF2EventTracker") {
        return false;
    }

    env.cpu.regs_mut()[0] = receiver.to_bits();
    log!("ZombieFarm2 workaround: host-handled [{} init]", class_name);
    true
}

fn zombie_farm_return_open_udid(env: &mut Environment, receiver: id, selector_name: &str) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || !matches!(
            selector_name,
            "value" | "valueWithError:" | "_getOpenUDID" | "_generateFreshOpenUDID"
        )
    {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };
    if !matches!(
        class_name.as_str(),
        "VungleOpenUDID" | "OpenUDID" | "AP_OpenUDID"
    ) {
        return false;
    }

    let udid =
        ns_string::from_rust_string(env, "0000000000000000000000000000000000000000".to_string());
    env.cpu.regs_mut()[0] = udid.to_bits();
    log!(
        "ZombieFarm2 workaround: [{} {}] -> fixed OpenUDID",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_skip_vungle_ad_sdk(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };

    let should_skip = if class_name == "VungleSDK" {
        matches!(
            selector_name,
            "startWithAppId:"
                | "startWithAppId:delegate:"
                | "loadDatabase"
                | "updateUserAgent"
                | "setSafariUserAgent:"
                | "setDelegate:"
                | "setLoggingEnabled:"
                | "setUserData:"
                | "setIncentivizedDelegate:"
                | "cacheAd"
                | "playAd"
                | "getPreferenceValueForKey:"
                | "setPreferenceValue:forKey:"
        )
    } else if class_name == "VungleCacheManager" {
        matches!(selector_name, "createDirectory:")
    } else if class_name.starts_with("VungleFMDatabaseQueue") {
        matches!(
            selector_name,
            "inDatabase:"
                | "inTransaction:"
                | "inDeferredTransaction:"
                | "database"
                | "close"
                | "checkpoint:error:"
        )
    } else if class_name.starts_with("VungleFMDatabase") {
        matches!(
            selector_name,
            "open"
                | "openWithFlags:"
                | "close"
                | "executeQuery:"
                | "executeQuery:withArgumentsInArray:orDictionary:orVAList:"
                | "executeUpdate:"
                | "executeUpdate:withArgumentsInArray:orDictionary:orVAList:"
                | "executeStatements:"
                | "lastErrorCode"
                | "lastErrorMessage"
        )
    } else {
        false
    };

    if !should_skip {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping Vungle ad SDK [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_skip_broken_font_preload(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || !matches!(
            selector_name,
            "loadFonts" | "loadFont:" | "loadFont:withName:"
        )
        || zombie_farm_object_class_name(env, receiver) != Some("ZombieFarmAppDelegate")
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping ZombieFarmAppDelegate {}",
        selector_name
    );
    true
}

fn zombie_farm_skip_brain_client_network(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };

    let should_skip = if class_name == "BrainClient" {
        selector_name.starts_with("sendRequestTo:")
            || matches!(
                selector_name,
                "cancelRequestsForDelegate:"
                    | "setAsynchronousOperations:"
                    | "setSynchronousOperations:"
            )
    } else if class_name == "BrainClientOperation" {
        matches!(
            selector_name,
            "start"
                | "main"
                | "createPostRequest"
                | "sendRequest"
                | "connection:didReceiveResponse:"
                | "connection:didReceiveData:"
                | "connectionDidFinishLoading:"
                | "connection:didFailWithError:"
        )
    } else if class_name == "NSOperationQueue" && selector_name == "addOperation:" {
        let operation = id::from_bits(env.cpu.regs()[2]);
        zombie_farm_object_class_name(env, operation) == Some("BrainClientOperation")
    } else {
        false
    };

    if !should_skip {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping BrainClient network [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_skip_sync_queue_network(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };

    let is_sync_operation = matches!(
        class_name.as_str(),
        "SyncOperation"
            | "SetupOperation"
            | "SetupActiveOperation"
            | "LoadSaveOperation"
            | "SyncSaveOperation"
            | "DownloadSaveOperation"
            | "UploadSaveOperation"
            | "SaveGameOperation"
    );
    if is_sync_operation
        && matches!(
            selector_name,
            "initWithManager:andDelegate:" | "initWithManager:delegate:" | "initWithDelegate:"
        )
    {
        let (manager, delegate) = if selector_name == "initWithDelegate:" {
            (nil, id::from_bits(env.cpu.regs()[2]))
        } else {
            (
                id::from_bits(env.cpu.regs()[2]),
                id::from_bits(env.cpu.regs()[3]),
            )
        };
        zombie_farm_sync_operations().lock().unwrap().insert(
            receiver.to_bits(),
            ZombieFarmSyncOperationInfo {
                manager: manager.to_bits(),
                delegate: delegate.to_bits(),
            },
        );
        env.cpu.regs_mut()[0] = receiver.to_bits();
        log!(
            "ZombieFarm2 workaround: host-handled SyncQueue operation init [{} {}] manager {:?} delegate {:?} ({})",
            class_name,
            selector_name,
            manager,
            delegate,
            zombie_farm_object_class_name(env, delegate).unwrap_or("unknown")
        );
        return true;
    }

    let should_skip = if class_name == "SyncQueue" {
        matches!(
            selector_name,
            "addOperation:"
                | "addOperation:withPriority:"
                | "addOperations:waitUntilFinished:"
                | "cancelAllOperations"
        )
    } else if is_sync_operation {
        matches!(selector_name, "start" | "main" | "cancel")
    } else if class_name == "NSOperationQueue" && selector_name == "addOperation:" {
        let operation = id::from_bits(env.cpu.regs()[2]);
        zombie_farm_object_class_name(env, operation).is_some_and(|operation_class| {
            operation_class == "SyncOperation"
                || operation_class == "SetupOperation"
                || operation_class.ends_with("Operation") && operation_class.contains("Save")
                || operation_class == "SetupActiveOperation"
        })
    } else {
        false
    };

    if !should_skip {
        return false;
    }

    let skipped_setup_active_operation = matches!(
        selector_name,
        "addOperation:" | "addOperation:withPriority:"
    ) && {
        let operation = id::from_bits(env.cpu.regs()[2]);
        matches!(
            zombie_farm_object_class_name(env, operation),
            Some("SetupOperation" | "SetupActiveOperation")
        )
    };
    if skipped_setup_active_operation {
        let operation = id::from_bits(env.cpu.regs()[2]);
        zombie_farm_complete_skipped_setup_operation(env, operation);
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping SyncQueue network [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_complete_skipped_setup_operation(env: &mut Environment, operation: id) {
    let info = zombie_farm_sync_operations()
        .lock()
        .unwrap()
        .get(&operation.to_bits())
        .copied();
    let Some(info) = info else {
        zombie_farm_finish_skipped_startup_sync(env);
        return;
    };

    let delegate = id::from_bits(info.delegate);
    let manager = id::from_bits(info.manager);
    log!(
        "ZombieFarm2 workaround: completing skipped {:?} ({}) manager {:?} delegate {:?} ({})",
        operation,
        zombie_farm_object_class_name(env, operation).unwrap_or("unknown"),
        manager,
        delegate,
        zombie_farm_object_class_name(env, delegate).unwrap_or("unknown")
    );

    if zombie_farm_object_class_name(env, delegate) == Some("LoadingScreen")
        && zombie_farm_send_noarg_if_responds(env, delegate, "loadFarmScene")
    {
        let _ = zombie_farm_remove_view_controller_view(env, delegate, "LoadingScreen");
        if let Some(main_menu) = zombie_farm_last_main_menu() {
            let _ = zombie_farm_remove_view_controller_view(env, main_menu, "MainMenu");
        }
        zombie_farm_remove_stale_uikit_subviews_by_class(env, "WhiteDimLayer");
        zombie_farm_reveal_hud_controls(env, "LoadingScreen loadFarmScene");
        zombie_farm_finish_skipped_startup_sync(env);
        return;
    }

    let sent_sync_finished = zombie_farm_send_noarg_if_responds(env, delegate, "syncFinished");
    if zombie_farm_get_farm_tile_map(env).is_none() {
        zombie_farm_send_noarg_if_responds(env, delegate, "startGame");
    }
    if !sent_sync_finished && zombie_farm_get_farm_tile_map(env).is_none() {
        zombie_farm_finish_skipped_startup_sync(env);
    }
}

fn zombie_farm_finish_skipped_startup_sync(env: &mut Environment) {
    let Some(gui_layer) = zombie_farm_get_gui_layer(env) else {
        return;
    };
    let Some(startup_complete_selector) = env.objc.lookup_selector("startUpChecksComplete") else {
        return;
    };
    if !env
        .objc
        .object_has_method(&env.mem, gui_layer, startup_complete_selector)
    {
        return;
    }

    let regs = *env.cpu.regs();
    log!("ZombieFarm2 workaround: completing skipped startup sync locally");
    let _: () = msg_send_no_type_checking(env, (gui_layer, startup_complete_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    zombie_farm_reveal_hud_controls(env, "startup sync");
}

fn zombie_farm_return_safe_game_state_count(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("GameState")
    {
        return false;
    }

    let value = match selector_name {
        "curArmySize" | "armySize" => 0,
        "maxArmySize" => 8,
        _ => return false,
    };

    env.cpu.regs_mut()[0] = value;
    log!(
        "ZombieFarm2 workaround: [{} {}] -> {}",
        "GameState",
        selector_name,
        value
    );
    true
}

fn zombie_farm_skip_remote_dependent_game_state_update(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("GameState")
        || selector_name != "updateRemoteDataDependantSystems"
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!("ZombieFarm2 workaround: skipping [GameState updateRemoteDataDependantSystems]");
    true
}

fn zombie_farm_return_self_for_game_data_copy(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("GameData")
        || !matches!(
            selector_name,
            "copyWithZone:" | "mutableCopyWithZone:" | "copy"
        )
    {
        return false;
    }

    env.cpu.regs_mut()[0] = retain(env, receiver).to_bits();
    log!(
        "ZombieFarm2 workaround: returning retained self for [GameData {}]",
        selector_name
    );
    true
}

pub(super) fn zombie_farm_should_return_self_for_unimplemented_cocos_reverse(
    zombie_farm_bundle: bool,
    receiver_class_name: &str,
    implementation_class_name: &str,
    selector_name: &str,
) -> bool {
    zombie_farm_bundle
        && selector_name == "reverse"
        && receiver_class_name.starts_with("CC")
        && matches!(
            implementation_class_name,
            "CCAction" | "CCFiniteTimeAction" | "CCIntervalAction"
        )
}

fn zombie_farm_host_actor_manager_init(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("ZFActorManager")
    {
        return false;
    }

    if matches!(selector_name, "deleteAllFarmActors" | "removeAllActors") {
        env.cpu.regs_mut()[0] = 0;
        log!(
            "ZombieFarm2 workaround: skipping [ZFActorManager {}]",
            selector_name
        );
        return true;
    }

    false
}

fn zombie_farm_skip_tool_manager_transient_actions(
    _env: &mut Environment,
    _receiver: id,
    _selector_name: &str,
) -> bool {
    false
}

fn zombie_farm_skip_quest_manager_reset(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("ZFQuestMan")
        || !matches!(selector_name, "reset" | "enable:")
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping [ZFQuestMan {}]",
        selector_name
    );
    true
}

fn zombie_farm_restore_local_quest_progress(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) {
    if !zombie_farm_uses_playforge_bundle(env)
        || !matches!(selector_name, "statusCheckDone" | "startUpChecksComplete")
    {
        return;
    }

    static RESTORED: AtomicBool = AtomicBool::new(false);
    if RESTORED.swap(true, Ordering::Relaxed) {
        return;
    }

    let regs = *env.cpu.regs();
    let gui_layer = if zombie_farm_object_class_name(env, receiver) == Some("ZFGuiLayer") {
        Some(receiver)
    } else {
        zombie_farm_get_gui_layer(env)
    };
    let quest_man = zombie_farm_get_quest_man(env);
    if gui_layer.is_none() && quest_man.is_none() {
        log!(
            "ZombieFarm workaround: quest restore skipped after {} because guiLayer and questMan are both unavailable",
            selector_name
        );
        env.cpu.regs_mut().copy_from_slice(&regs);
        RESTORED.store(false, Ordering::Relaxed);
        return;
    }

    zombie_farm_log_local_quest_restore_snapshot(
        env,
        "before local quest restore",
        gui_layer,
        quest_man,
    );

    let mut restored_any = false;
    if let Some(gui_layer) = gui_layer {
        if zombie_farm_send_noarg_if_responds(env, gui_layer, "restoreQuestsFromSave") {
            log!(
                "ZombieFarm workaround: invoked [ZFGuiLayer restoreQuestsFromSave] after {}",
                selector_name
            );
            restored_any = true;
        }
        if zombie_farm_send_noarg_if_responds(env, gui_layer, "updateStats") {
            log!(
                "ZombieFarm workaround: invoked [ZFGuiLayer updateStats] after {}",
                selector_name
            );
            restored_any = true;
        }
        if zombie_farm_send_noarg_if_responds(env, gui_layer, "getActiveProfileStatus") {
            log!(
                "ZombieFarm workaround: invoked [ZFGuiLayer getActiveProfileStatus] after {}",
                selector_name
            );
            restored_any = true;
        }
    }

    if let Some(quest_man) = quest_man {
        if zombie_farm_send_noarg_if_responds(env, quest_man, "restoreQuestsFromSave") {
            log!(
                "ZombieFarm workaround: invoked [ZFQuestMan restoreQuestsFromSave] after {}",
                selector_name
            );
            restored_any = true;
        }
        let replayed = zombie_farm_replay_loot_item_notifications_from_inventory(env, quest_man);
        if replayed > 0 {
            restored_any = true;
            log!(
                "ZombieFarm workaround: replayed {} offline loot quest notification(s) after {}",
                replayed,
                selector_name
            );
        }
        if zombie_farm_send_noarg_if_responds(env, quest_man, "updateStats") {
            log!(
                "ZombieFarm workaround: invoked [ZFQuestMan updateStats] after {}",
                selector_name
            );
            restored_any = true;
        }
        if zombie_farm_send_noarg_if_responds(env, quest_man, "getActiveProfileStatus") {
            log!(
                "ZombieFarm workaround: invoked [ZFQuestMan getActiveProfileStatus] after {}",
                selector_name
            );
            restored_any = true;
        }
    }

    zombie_farm_log_local_quest_restore_snapshot(
        env,
        "after local quest restore",
        gui_layer,
        quest_man,
    );

    if !restored_any {
        log!(
            "ZombieFarm workaround: no local quest restore selector matched after {}",
            selector_name
        );
        RESTORED.store(false, Ordering::Relaxed);
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_skip_unsafe_toolbar_build(
    _env: &mut Environment,
    _receiver: id,
    _selector_name: &str,
) -> bool {
    false
}

fn zombie_farm_skip_market_offers(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("MarketDataManager")
        || !matches!(selector_name, "offersAvailable" | "hasOffersAvailable")
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: treating [MarketDataManager {}] as false",
        selector_name
    );
    true
}

fn zombie_farm_skip_event_ad_networks(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };

    let should_skip = if matches!(class_name.as_str(), "EventTracker" | "ZF2EventTracker") {
        matches!(
            selector_name,
            "setupAdNetworks"
                | "setupFlurryAds"
                | "fetchFlurryAds"
                | "fetchFlurryAdForSpace:"
                | "isFlurryAdAvailableForSpace:"
                | "setupKiipAds"
                | "showFlurryAdForSpace:"
                | "showKiipAd:"
        )
    } else {
        class_name == "Kiip"
            || class_name.starts_with("Kiip")
            || class_name == "Flurry"
            || class_name.starts_with("Flurry")
            || class_name == "Chartboost"
            || class_name.starts_with("Chartboost")
            || class_name.starts_with("AdColony")
            || class_name.starts_with("ADC")
    };

    if !should_skip {
        return false;
    }

    env.cpu.regs_mut()[0] = if selector_name.starts_with("init") {
        receiver.to_bits()
    } else {
        0
    };
    log!(
        "ZombieFarm2 workaround: skipping ad network [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_skip_startup_profile_detection(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("PlayerProfileManager")
        || !matches!(
            selector_name,
            "determineStartupPlayer"
                | "determineStartupPlayer:"
                | "updatePlayerInfo"
                | "showStartupPlayerSelection"
                | "showStartupPlayerSelection:"
        )
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping PlayerProfileManager {}",
        selector_name
    );
    true
}

fn zombie_farm_skip_startup_internet_loading(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };
    let should_skip = (class_name == "MainMenu" && selector_name == "startupInternet")
        || (class_name == "LoadingScreen"
            && matches!(
                selector_name,
                "updateLoadingScreens" | "show" | "hide" | "show:" | "hide:"
            ));

    if !should_skip {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping startup loading [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_host_load_farm_scene(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("LoadingScreen")
        || selector_name != "loadFarmScene"
        || std::env::var("TOUCHHLE_ZF2_HOST_LOAD_SCENE")
            .ok()
            .as_deref()
            != Some("1")
    {
        return false;
    }

    let regs = *env.cpu.regs();
    let game_data = zombie_farm_get_game_data(env).unwrap_or(nil);
    let scene_class = env.objc.get_known_class("ZFFarmGameScene", &mut env.mem);
    let scene: id = if let Some(node_selector) = env.objc.lookup_selector("node") {
        if env
            .objc
            .object_has_method(&env.mem, scene_class, node_selector)
        {
            msg_send_no_type_checking(env, (scene_class, node_selector))
        } else {
            nil
        }
    } else {
        nil
    };
    let scene: id = if scene != nil {
        scene
    } else {
        let Some(alloc_selector) = env.objc.lookup_selector("alloc") else {
            return false;
        };
        let Some(init_selector) = env.objc.lookup_selector("init") else {
            return false;
        };
        let allocated_scene: id = msg_send_no_type_checking(env, (scene_class, alloc_selector));
        if allocated_scene == nil {
            nil
        } else {
            msg_send_no_type_checking(env, (allocated_scene, init_selector))
        }
    };
    if scene == nil {
        env.cpu.regs_mut().copy_from_slice(&regs);
        return false;
    }

    if game_data != nil {
        if let Some(load_scene_selector) = env.objc.lookup_selector("loadSceneWithGameData:") {
            if env
                .objc
                .object_has_method(&env.mem, scene, load_scene_selector)
            {
                let _: () = msg_send_no_type_checking(env, (scene, load_scene_selector, game_data));
            }
        }
    }
    if let Some(startup_selector) = env.objc.lookup_selector("startup") {
        if env
            .objc
            .object_has_method(&env.mem, scene, startup_selector)
        {
            let _: () = msg_send_no_type_checking(env, (scene, startup_selector));
        }
    }

    let director_class = env.objc.get_known_class("CCDirector", &mut env.mem);
    if let Some(shared_director_selector) = env.objc.lookup_selector("sharedDirector") {
        let director: id =
            msg_send_no_type_checking(env, (director_class, shared_director_selector));
        if director != nil {
            let running_scene =
                if let Some(running_scene_selector) = env.objc.lookup_selector("runningScene") {
                    if env
                        .objc
                        .object_has_method(&env.mem, director, running_scene_selector)
                    {
                        msg_send_no_type_checking(env, (director, running_scene_selector))
                    } else {
                        nil
                    }
                } else {
                    nil
                };
            let scene_selector_name = if running_scene == nil {
                "runWithScene:"
            } else {
                "replaceScene:"
            };
            if let Some(scene_selector) = env.objc.lookup_selector(scene_selector_name) {
                if env
                    .objc
                    .object_has_method(&env.mem, director, scene_selector)
                {
                    let _: () = msg_send_no_type_checking(env, (director, scene_selector, scene));
                }
            }
        }
    }

    let tile_map = zombie_farm_get_farm_tile_map(env).unwrap_or(nil);
    let main_menu = zombie_farm_last_main_menu();
    let _ = zombie_farm_remove_view_controller_view(env, receiver, "LoadingScreen");
    if let Some(main_menu) = main_menu {
        let _ = zombie_farm_remove_view_controller_view(env, main_menu, "MainMenu");
    }
    zombie_farm_reveal_hud_controls(env, "host loadFarmScene");
    zombie_farm_finish_skipped_startup_sync(env);
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: host-loaded farm scene {:?}, tile map {:?}",
        scene,
        tile_map
    );
    true
}

fn zombie_farm_skip_farmer_head_modal(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("FarmerHeadMenu")
        || selector_name != "open"
    {
        return false;
    }

    let regs = *env.cpu.regs();
    if let Some(select_selector) = env.objc.lookup_selector("selectHeadIndex:") {
        if env
            .objc
            .object_has_method(&env.mem, receiver, select_selector)
        {
            let _: () = msg_send_no_type_checking(env, (receiver, select_selector, 0i32));
        }
    }
    env.cpu.regs_mut().copy_from_slice(&regs);

    let regs = *env.cpu.regs();
    if let Some(selected_selector) = env.objc.lookup_selector("headSelected") {
        if env
            .objc
            .object_has_method(&env.mem, receiver, selected_selector)
        {
            let _: () = msg_send_no_type_checking(env, (receiver, selected_selector));
        }
    }
    env.cpu.regs_mut().copy_from_slice(&regs);

    let _ = zombie_farm_remove_view_controller_view(env, receiver, "FarmerHeadMenu");
    zombie_farm_remove_stale_uikit_subviews_by_class(env, "WhiteDimLayer");
    zombie_farm_reveal_hud_controls(env, "FarmerHeadMenu");
    zombie_farm_finish_skipped_startup_sync(env);
    env.cpu.regs_mut()[0] = 0;
    log!("ZombieFarm2 workaround: selected default farmer head and skipped FarmerHeadMenu open");
    true
}

fn zombie_farm_skip_cocos_denshion_effects(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return false;
    }

    let Some(class_name) = zombie_farm_object_class_name(env, receiver).map(str::to_string) else {
        return false;
    };

    let should_skip = if class_name == "SimpleAudioEngine" {
        matches!(
            selector_name,
            "playEffect:"
                | "playEffect:pitch:pan:gain:"
                | "preloadEffect:"
                | "unloadEffect:"
                | "stopEffect:"
        )
    } else if class_name == "CDBufferManager" {
        matches!(
            selector_name,
            "bufferForFile:create:" | "releaseBufferForFile:"
        )
    } else if class_name == "CDSoundEngine" {
        matches!(
            selector_name,
            "loadBuffer:filePath:"
                | "loadBufferFromData:soundData:format:size:freq:"
                | "playSound:sourceGroupId:pitch:pan:gain:loop:"
                | "stopSound:"
                | "stopAllSounds"
        )
    } else {
        false
    };

    if !should_skip {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping CocosDenshion effect [{} {}]",
        class_name,
        selector_name
    );
    true
}

fn zombie_farm_route_eagl_view_touches(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("EAGLView")
        || !matches!(
            selector_name,
            "touchesBegan:withEvent:"
                | "touchesMoved:withEvent:"
                | "touchesEnded:withEvent:"
                | "touchesCancelled:withEvent:"
        )
    {
        return false;
    }

    let dispatcher_class = env.objc.get_known_class("CCTouchDispatcher", &mut env.mem);
    let Some(shared_dispatcher_selector) = env.objc.lookup_selector("sharedDispatcher") else {
        return false;
    };
    if !env
        .objc
        .object_has_method(&env.mem, dispatcher_class, shared_dispatcher_selector)
    {
        return false;
    }
    let Some(touch_selector) = env.objc.lookup_selector(selector_name) else {
        return false;
    };

    let touches = id::from_bits(env.cpu.regs()[2]);
    let event = id::from_bits(env.cpu.regs()[3]);
    let regs = *env.cpu.regs();
    let dispatcher: id =
        msg_send_no_type_checking(env, (dispatcher_class, shared_dispatcher_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    if dispatcher == nil
        || !env
            .objc
            .object_has_method(&env.mem, dispatcher, touch_selector)
    {
        return false;
    }

    let regs = *env.cpu.regs();
    let _: () = msg_send_no_type_checking(env, (dispatcher, touch_selector, touches, event));
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: routed [EAGLView {}] to CCTouchDispatcher {:?}",
        selector_name,
        dispatcher
    );
    true
}

fn zombie_farm_host_cocos_touch_dispatcher(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || zombie_farm_object_class_name(env, receiver) != Some("CCTouchDispatcher")
    {
        return false;
    }

    match selector_name {
        "addTargetedDelegate:priority:swallowsTouches:" => {
            let delegate = id::from_bits(env.cpu.regs()[2]);
            if zombie_farm_object_pointer_looks_valid(env, delegate) {
                let mut handlers = zombie_farm_cocos_touch_handlers().lock().unwrap();
                let entry = handlers.entry(receiver.to_bits()).or_default();
                let delegate_bits = delegate.to_bits();
                if !entry.targeted.contains(&delegate_bits) {
                    entry.targeted.push(delegate_bits);
                }
                log!(
                    "ZombieFarm2 workaround: host CCTouchDispatcher add targeted delegate {:?} ({})",
                    delegate,
                    zombie_farm_object_class_name(env, delegate).unwrap_or("unknown")
                );
            }
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "addStandardDelegate:priority:" => {
            let delegate = id::from_bits(env.cpu.regs()[2]);
            if zombie_farm_object_pointer_looks_valid(env, delegate) {
                let mut handlers = zombie_farm_cocos_touch_handlers().lock().unwrap();
                let entry = handlers.entry(receiver.to_bits()).or_default();
                let delegate_bits = delegate.to_bits();
                if !entry.standard.contains(&delegate_bits) {
                    entry.standard.push(delegate_bits);
                }
                log!(
                    "ZombieFarm2 workaround: host CCTouchDispatcher add standard delegate {:?} ({})",
                    delegate,
                    zombie_farm_object_class_name(env, delegate).unwrap_or("unknown")
                );
            }
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "removeDelegate:" => {
            let delegate_bits = env.cpu.regs()[2];
            let mut handlers = zombie_farm_cocos_touch_handlers().lock().unwrap();
            if let Some(entry) = handlers.get_mut(&receiver.to_bits()) {
                entry.targeted.retain(|&value| value != delegate_bits);
                entry.standard.retain(|&value| value != delegate_bits);
                for claimed in entry.claimed_targeted.values_mut() {
                    claimed.retain(|&value| value != delegate_bits);
                }
            }
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "removeAllDelegates" => {
            zombie_farm_cocos_touch_handlers()
                .lock()
                .unwrap()
                .remove(&receiver.to_bits());
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "dispatchEvents" => {
            env.cpu.regs_mut()[0] = 1;
            true
        }
        "setDispatchEvents:" => {
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "touchesBegan:withEvent:"
        | "touchesMoved:withEvent:"
        | "touchesEnded:withEvent:"
        | "touchesCancelled:withEvent:" => {
            zombie_farm_dispatch_cocos_touches(env, receiver, selector_name);
            env.cpu.regs_mut()[0] = 0;
            true
        }
        "touches:withEvent:withTouchType:" => {
            env.cpu.regs_mut()[0] = 0;
            log!("ZombieFarm2 workaround: ignoring raw CCTouchDispatcher touch multiplexer");
            true
        }
        _ => false,
    }
}

fn zombie_farm_dispatch_cocos_touches(env: &mut Environment, dispatcher: id, selector_name: &str) {
    let mut handlers = zombie_farm_cocos_touch_handlers()
        .lock()
        .unwrap()
        .get(&dispatcher.to_bits())
        .cloned()
        .unwrap_or_default();

    let regs = *env.cpu.regs();
    let fallback_touch_delegate = zombie_farm_get_farm_tile_map(env);
    env.cpu.regs_mut().copy_from_slice(&regs);
    if let Some(touch_delegate) = fallback_touch_delegate {
        let delegate_bits = touch_delegate.to_bits();
        if !handlers.targeted.contains(&delegate_bits) {
            log!(
                "ZombieFarm2 workaround: adding {:?} ({}) as fallback Cocos touch delegate",
                touch_delegate,
                zombie_farm_object_class_name(env, touch_delegate).unwrap_or("unknown")
            );
            handlers.targeted.push(delegate_bits);
        }
    }

    if handlers.targeted.is_empty() && handlers.standard.is_empty() {
        log!(
            "ZombieFarm2 workaround: no Cocos touch delegates for {}",
            selector_name
        );
        return;
    }

    let touches = id::from_bits(env.cpu.regs()[2]);
    let event = id::from_bits(env.cpu.regs()[3]);
    let Some(any_object_selector) = env.objc.lookup_selector("anyObject") else {
        return;
    };
    let regs = *env.cpu.regs();
    let touch: id = msg_send_no_type_checking(env, (touches, any_object_selector));
    env.cpu.regs_mut().copy_from_slice(&regs);
    if touch == nil {
        return;
    }
    let touch_bits = touch.to_bits();
    let touch_trace_enabled = zombie_farm_touch_trace_enabled();
    if touch_trace_enabled {
        if let Some(location_selector) = env.objc.lookup_selector("locationInView:") {
            let regs = *env.cpu.regs();
            let location: CGPoint = msg_send_no_type_checking(env, (touch, location_selector, nil));
            env.cpu.regs_mut().copy_from_slice(&regs);
            log!(
                "ZombieFarm2 touch trace: dispatch {} touch {:?} location {} targeted={} standard={}",
                selector_name,
                touch,
                location,
                handlers.targeted.len(),
                handlers.standard.len(),
            );
        }
    }

    let (targeted_selector_name, standard_selector_name, targeted_returns_bool) =
        match selector_name {
            "touchesBegan:withEvent:" => {
                ("ccTouchBegan:withEvent:", "ccTouchesBegan:withEvent:", true)
            }
            "touchesMoved:withEvent:" => (
                "ccTouchMoved:withEvent:",
                "ccTouchesMoved:withEvent:",
                false,
            ),
            "touchesEnded:withEvent:" => (
                "ccTouchEnded:withEvent:",
                "ccTouchesEnded:withEvent:",
                false,
            ),
            "touchesCancelled:withEvent:" => (
                "ccTouchCancelled:withEvent:",
                "ccTouchesCancelled:withEvent:",
                false,
            ),
            _ => return,
        };

    if let Some(targeted_selector) = env.objc.lookup_selector(targeted_selector_name) {
        let targeted_delegates = if selector_name == "touchesBegan:withEvent:" {
            handlers.targeted.clone()
        } else {
            let claimed = handlers
                .claimed_targeted
                .get(&touch_bits)
                .cloned()
                .unwrap_or_default();
            if claimed.is_empty() {
                log_dbg!(
                    "ZombieFarm2 workaround: no claimed Cocos touch delegates for {}, falling back to registered targeted delegates",
                    selector_name
                );
                handlers.targeted.clone()
            } else {
                claimed
            }
        };
        let mut claimed_delegates = Vec::new();
        for delegate_bits in targeted_delegates {
            let delegate = id::from_bits(delegate_bits);
            if !zombie_farm_object_pointer_looks_valid(env, delegate)
                || !env
                    .objc
                    .object_has_method(&env.mem, delegate, targeted_selector)
            {
                continue;
            }
            let regs = *env.cpu.regs();
            if targeted_returns_bool {
                let claimed: bool =
                    msg_send_no_type_checking(env, (delegate, targeted_selector, touch, event));
                if claimed {
                    claimed_delegates.push(delegate_bits);
                }
                log_dbg!(
                    "ZombieFarm2 workaround: [{} ccTouchBegan] returned {}",
                    zombie_farm_object_class_name(env, delegate).unwrap_or("unknown"),
                    claimed
                );
                if touch_trace_enabled {
                    log!(
                        "ZombieFarm2 touch trace: [{} ccTouchBegan] returned {}",
                        zombie_farm_object_class_name(env, delegate).unwrap_or("unknown"),
                        claimed
                    );
                }
            } else {
                let _: () =
                    msg_send_no_type_checking(env, (delegate, targeted_selector, touch, event));
                if touch_trace_enabled {
                    log!(
                        "ZombieFarm2 touch trace: sent [{} {}]",
                        zombie_farm_object_class_name(env, delegate).unwrap_or("unknown"),
                        targeted_selector_name
                    );
                }
            }
            env.cpu.regs_mut().copy_from_slice(&regs);
        }
        if selector_name == "touchesBegan:withEvent:" {
            let mut all_handlers = zombie_farm_cocos_touch_handlers().lock().unwrap();
            let entry = all_handlers.entry(dispatcher.to_bits()).or_default();
            if claimed_delegates.is_empty() {
                entry.claimed_targeted.remove(&touch_bits);
            } else {
                entry.claimed_targeted.insert(touch_bits, claimed_delegates);
            }
        } else if matches!(
            selector_name,
            "touchesEnded:withEvent:" | "touchesCancelled:withEvent:"
        ) {
            let mut all_handlers = zombie_farm_cocos_touch_handlers().lock().unwrap();
            if let Some(entry) = all_handlers.get_mut(&dispatcher.to_bits()) {
                entry.claimed_targeted.remove(&touch_bits);
            }
        }
    }

    if let Some(standard_selector) = env.objc.lookup_selector(standard_selector_name) {
        for delegate_bits in handlers.standard {
            let delegate = id::from_bits(delegate_bits);
            if !zombie_farm_object_pointer_looks_valid(env, delegate)
                || !env
                    .objc
                    .object_has_method(&env.mem, delegate, standard_selector)
            {
                continue;
            }
            let regs = *env.cpu.regs();
            let _: () =
                msg_send_no_type_checking(env, (delegate, standard_selector, touches, event));
            env.cpu.regs_mut().copy_from_slice(&regs);
        }
    }
}

fn zombie_farm_skip_unsafe_cocos_touch_dispatch(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || !matches!(selector_name, "touchesCancelled:withEvent:")
        || zombie_farm_object_class_name(env, receiver) != Some("CCTouchDispatcher")
    {
        return false;
    }

    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm2 workaround: skipping unsafe CCTouchDispatcher {}",
        selector_name
    );
    true
}

fn zombie_farm_trace_game_interaction_message(
    env: &Environment,
    receiver: id,
    selector_name: &str,
) {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2" {
        return;
    }

    if !zombie_farm_touch_trace_enabled() {
        return;
    }

    if !matches!(
        selector_name,
        "tileTapped:"
            | "actorTapped:"
            | "touchedTileNodeForLocation:checkDimensions:"
            | "tileFromScreenPoint:considerOffMap:"
            | "validTile:"
            | "touched:checkDimensions:"
            | "onTileClickUp:forTool:"
            | "onActorClickUp:forTool:"
            | "attemptToPlaceItemAtPoint:"
            | "placeToolOnNearestTileToPointOnMap:forTool:"
            | "pushGameAction:onTile:withRect:withItem:"
            | "popGameActionAndExecute:"
            | "setCurrentPlayerAction:"
            | "currentPlayerAction"
            | "clearMap"
            | "harvestPlantCropAt:"
            | "harvestZombieCropAt:"
            | "isPlantCrop"
            | "isZombieCrop"
            | "isHarvestable"
            | "ready"
            | "timeLeftToHarvestCropTile:"
            | "isTilePlantable:"
            | "canPlaceTileOfSize:at:"
            | "tutorialZombieHarvested"
            | "selectTool:withLabel:withImage:"
            | "selectTool:withLabel:"
            | "toolSelected:"
            | "currentGameTool"
            | "setCurrentGameTool:"
            | "toolCleanup:"
            | "payForItemFromTool:"
            | "deductResourceForAction:"
            | "clearAllGameActions"
            | "menuTapped"
            | "marketTapped"
            | "itemTapped:"
            | "questJournalTapped"
            | "goldBarTapped"
            | "brainsBarTapped"
    ) {
        return;
    }

    let stack_detail = if selector_name == "onTileClickUp:forTool:" {
        let stack_tool: u32 = env.mem.read(ConstPtr::from_bits(env.cpu.regs()[Cpu::SP]));
        format!(" stack_tool={}", stack_tool)
    } else {
        String::new()
    };

    log!(
        "ZombieFarm2 touch trace: [{} {}] r2=0x{:x} r3=0x{:x}{}",
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
        selector_name,
        env.cpu.regs()[2],
        env.cpu.regs()[3],
        stack_detail,
    );
}

fn zombie_farm_force_status_bar_timeout(env: &mut Environment, receiver: id, selector_name: &str) {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
    {
        return;
    }

    let is_status_bar_message = selector_name == "statusMessage:cancelAfter:";
    let is_status_bar_view_message = zombie_farm_object_class_name(env, receiver)
        == Some("StatusBar")
        && matches!(
            selector_name,
            "showMessage:withCancelTimeout:andCancelNotification:"
                | "updateMessage:andCancelTimeout:andCancelNotification:"
        );
    if !is_status_bar_message && !is_status_bar_view_message {
        return;
    }

    let regs = *env.cpu.regs();
    let timeout: id = msg_class![env; NSNumber numberWithFloat:1.0f32];
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[3] = timeout.to_bits();
    log!(
        "ZombieFarm workaround: forcing [StatusBar {}] timeout to 1s",
        selector_name
    );
    zombie_farm_schedule_status_bar_hide(env, receiver);
}

fn zombie_farm_schedule_delayed_noarg_selector(
    env: &mut Environment,
    target: id,
    selector_name: &str,
    delay: f64,
) -> bool {
    if target == nil {
        return false;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return false;
    };
    if !env.objc.object_has_method(&env.mem, target, selector) {
        return false;
    }
    let Some(delayed_selector) = env
        .objc
        .lookup_selector("performSelector:withObject:afterDelay:")
    else {
        return false;
    };
    if !env
        .objc
        .object_has_method(&env.mem, target, delayed_selector)
    {
        return false;
    }

    let regs = *env.cpu.regs();
    let _: () = msg_send_no_type_checking(env, (target, delayed_selector, selector, nil, delay));
    env.cpu.regs_mut().copy_from_slice(&regs);
    true
}

fn zombie_farm_schedule_status_bar_hide(env: &mut Environment, receiver: id) {
    let regs = *env.cpu.regs();
    let status_bar_class = env.objc.get_known_class("StatusBar", &mut env.mem);
    let status_bar = if let Some(status_bar_selector) = env.objc.lookup_selector("statusBar") {
        if env
            .objc
            .object_has_method(&env.mem, status_bar_class, status_bar_selector)
        {
            msg_send_no_type_checking(env, (status_bar_class, status_bar_selector))
        } else {
            nil
        }
    } else {
        nil
    };
    let status_bar =
        if status_bar == nil && zombie_farm_object_class_name(env, receiver) == Some("StatusBar") {
            receiver
        } else {
            status_bar
        };
    env.cpu.regs_mut().copy_from_slice(&regs);

    let scheduled_hide = zombie_farm_schedule_delayed_noarg_selector(env, status_bar, "hide", 1.0);

    let view = if status_bar != nil {
        let regs = *env.cpu.regs();
        let view = if let Some(view_selector) = env.objc.lookup_selector("view") {
            if env
                .objc
                .object_has_method(&env.mem, status_bar, view_selector)
            {
                msg_send_no_type_checking(env, (status_bar, view_selector))
            } else {
                nil
            }
        } else {
            nil
        };
        env.cpu.regs_mut().copy_from_slice(&regs);
        view
    } else {
        nil
    };
    let scheduled_remove =
        zombie_farm_schedule_delayed_noarg_selector(env, view, "removeFromSuperview", 1.0);

    log!(
        "ZombieFarm workaround: scheduled StatusBar cleanup in 1s (hide={}, removeView={})",
        scheduled_hide,
        scheduled_remove
    );
}

fn zombie_farm_trace_game_interaction_return(env: &Environment, receiver: id, selector_name: &str) {
    if env.bundle.bundle_identifier() != "com.playforge.ZombieFarm2"
        || !zombie_farm_touch_trace_enabled()
        || !matches!(
            zombie_farm_object_class_name(env, receiver),
            Some("ZFFarmTileMap" | "ZFTileManager" | "ZFToolManager" | "Tile")
        )
        || !matches!(
            selector_name,
            "touchedTileNodeForLocation:checkDimensions:"
                | "tileFromScreenPoint:considerOffMap:"
                | "validTile:"
                | "touched:checkDimensions:"
                | "harvestPlantCropAt:"
                | "harvestZombieCropAt:"
                | "isPlantCrop"
                | "isZombieCrop"
                | "isHarvestable"
                | "ready"
                | "timeLeftToHarvestCropTile:"
                | "isTilePlantable:"
                | "canPlaceTileOfSize:at:"
                | "toolSelected:"
        )
    {
        return;
    }

    log!(
        "ZombieFarm2 touch trace: [{} {}] -> r0=0x{:x}",
        zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
        selector_name,
        env.cpu.regs()[0],
    );
}

fn zombie_farm_actor_hunger(env: &mut Environment, actor: id) -> Option<f32> {
    if actor == nil {
        return None;
    }

    if let Some(hunger_selector) = env.objc.lookup_selector("hunger") {
        if env.objc.object_has_method(&env.mem, actor, hunger_selector) {
            return Some(msg_send_no_type_checking(env, (actor, hunger_selector)));
        }
    }

    let ivar_name = "hunger".to_string();
    let ivar = env.objc.object_lookup_ivar(&env.mem, actor, &ivar_name)?;
    Some(env.mem.read(ivar.cast()))
}

fn zombie_farm_set_actor_hunger(env: &mut Environment, actor: id, hunger: f32) -> bool {
    if actor == nil {
        return false;
    }

    if zombie_farm_actor_is_zombie(env, actor) {
        return zombie_farm_write_actor_hunger_ivar(env, actor, hunger.max(1.0).clamp(0.0, 1.0));
    }

    if let Some(set_hunger_selector) = env.objc.lookup_selector("setHunger:") {
        if env
            .objc
            .object_has_method(&env.mem, actor, set_hunger_selector)
        {
            let _: () = msg_send_no_type_checking(env, (actor, set_hunger_selector, hunger));
            return true;
        }
    }

    zombie_farm_write_actor_hunger_ivar(env, actor, hunger)
}

fn zombie_farm_force_zombie_hunger_in_list(env: &mut Environment, actor_list: id) -> (u32, u32) {
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return (0, 0);
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return (0, 0);
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return (0, 0);
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut zombies = 0u32;
    let mut changed = 0u32;
    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }
        zombies += 1;
        let old_hunger = zombie_farm_read_actor_hunger_ivar(env, actor).unwrap_or(0.0);
        if old_hunger < 0.999 && zombie_farm_write_actor_hunger_ivar(env, actor, 1.0) {
            changed += 1;
        }
    }
    (zombies, changed)
}

fn zombie_farm_force_all_zombie_hunger(env: &mut Environment, reason: &str) {
    if !zombie_farm_uses_playforge_bundle(env) {
        return;
    }

    let mut zombies = 0u32;
    let mut changed = 0u32;
    for actor_list in [
        zombie_farm_get_actor_list(env),
        zombie_farm_get_live_actor_list(env),
    ]
    .into_iter()
    .flatten()
    {
        let (list_zombies, list_changed) = zombie_farm_force_zombie_hunger_in_list(env, actor_list);
        zombies += list_zombies;
        changed += list_changed;
    }

    if zombies > 0 && changed > 0 {
        log_dbg!(
            "ZombieFarm status: force-filled hunger for {}/{} zombie actor entries before {}",
            changed,
            zombies,
            reason
        );
    }
}

fn zombie_farm_force_zombie_hunger_message(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }

    if selector_name == "getAverageHunger" {
        zombie_farm_force_all_zombie_hunger(env, "getAverageHunger");
        env.cpu.regs_mut()[0] = 1.0f32.to_bits();
        log_dbg!("ZombieFarm status: [getAverageHunger] -> 1.000");
        return true;
    }

    if !zombie_farm_actor_is_zombie(env, receiver) {
        return false;
    }

    match selector_name {
        "hunger" => {
            zombie_farm_write_actor_hunger_ivar(env, receiver, 1.0);
            env.cpu.regs_mut()[0] = 1.0f32.to_bits();
            true
        }
        "setHunger:" => {
            zombie_farm_write_actor_hunger_ivar(env, receiver, 1.0);
            env.cpu.regs_mut()[0] = 0;
            true
        }
        _ => false,
    }
}

fn zombie_farm_zombie_hungers_in_list(env: &mut Environment, actor_list: id) -> Vec<f32> {
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return Vec::new();
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return Vec::new();
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return Vec::new();
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut hungers = Vec::new();
    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }
        hungers.push(zombie_farm_actor_hunger(env, actor).unwrap_or(0.0));
    }
    hungers
}

fn zombie_farm_apply_zombie_hungers_to_list(
    env: &mut Environment,
    actor_list: id,
    target_hungers: &[f32],
) -> (u32, u32, f32) {
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return (0, 0, 0.0);
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return (0, 0, 0.0);
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return (0, 0, 0.0);
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut zombies = 0u32;
    let mut changed = 0u32;
    let mut max_hunger = 0.0f32;
    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }

        let Some(&target_hunger) = target_hungers.get(zombies as usize) else {
            break;
        };
        zombies += 1;
        let old_hunger = zombie_farm_actor_hunger(env, actor).unwrap_or(0.0);
        let new_hunger = old_hunger.max(target_hunger).clamp(0.0, 1.0);
        if new_hunger > old_hunger + 0.001 && zombie_farm_set_actor_hunger(env, actor, new_hunger) {
            changed += 1;
        }
        max_hunger = max_hunger.max(new_hunger);
    }

    (zombies, changed, max_hunger)
}

fn zombie_farm_sync_actor_hunger_lists(env: &mut Environment) -> (u32, u32, f32) {
    let lists = [
        zombie_farm_get_actor_list(env),
        zombie_farm_get_live_actor_list(env),
    ];
    let mut target_hungers = Vec::new();
    for actor_list in lists.into_iter().flatten() {
        for (idx, hunger) in zombie_farm_zombie_hungers_in_list(env, actor_list)
            .into_iter()
            .enumerate()
        {
            if idx == target_hungers.len() {
                target_hungers.push(hunger);
            } else if let Some(target) = target_hungers.get_mut(idx) {
                *target = (*target).max(hunger);
            }
        }
    }
    if target_hungers.is_empty() {
        return (0, 0, 0.0);
    }

    let mut zombies = 0u32;
    let mut changed = 0u32;
    let mut max_hunger = 0.0f32;
    for actor_list in [
        zombie_farm_get_actor_list(env),
        zombie_farm_get_live_actor_list(env),
    ]
    .into_iter()
    .flatten()
    {
        let (list_zombies, list_changed, list_max_hunger) =
            zombie_farm_apply_zombie_hungers_to_list(env, actor_list, &target_hungers);
        zombies += list_zombies;
        changed += list_changed;
        max_hunger = max_hunger.max(list_max_hunger);
    }

    if changed > 0 {
        log_dbg!(
            "ZombieFarm status: synced hunger for {}/{} zombie actor entries, max hunger {:.3}",
            changed,
            zombies,
            max_hunger
        );
    }
    (zombies, changed, max_hunger)
}

fn zombie_farm_zombie_eat_dates_near(
    env: &mut Environment,
    actor_list: id,
    date_interval: f64,
    tolerance: f64,
) -> (u32, u32) {
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return (0, 0);
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return (0, 0);
    };
    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return (0, 0);
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut zombies = 0u32;
    let mut near = 0u32;
    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }
        zombies += 1;
        if let Some(eat_date) = zombie_farm_actor_eat_date(env, actor) {
            if let Some(eat_interval) = zombie_farm_date_interval(env, eat_date) {
                if (eat_interval - date_interval).abs() <= tolerance {
                    near += 1;
                }
            }
        }
    }
    (zombies, near)
}

fn zombie_farm_apply_offline_actor_hunger_to_list(
    env: &mut Environment,
    actor_list: id,
    hunger_delta: f32,
    now: id,
    time_interval_since_date_selector: SEL,
    source_hungers: Option<&[f32]>,
) -> (u32, u32, f32) {
    let Some(count_selector) = env.objc.lookup_selector("count") else {
        return (0, 0, 0.0);
    };
    let Some(object_at_index_selector) = env.objc.lookup_selector("objectAtIndex:") else {
        return (0, 0, 0.0);
    };

    if !env
        .objc
        .object_has_method(&env.mem, actor_list, count_selector)
        || !env
            .objc
            .object_has_method(&env.mem, actor_list, object_at_index_selector)
    {
        return (0, 0, 0.0);
    }

    let count: NSUInteger = msg_send_no_type_checking(env, (actor_list, count_selector));
    let mut zombies = 0u32;
    let mut changed = 0u32;
    let mut max_hunger = 0.0f32;

    for idx in 0..count {
        let actor: id = msg_send_no_type_checking(env, (actor_list, object_at_index_selector, idx));
        if actor == nil || !zombie_farm_actor_is_zombie(env, actor) {
            continue;
        }
        let zombie_idx = zombies as usize;
        zombies += 1;

        let old_hunger = source_hungers
            .and_then(|hungers| hungers.get(zombie_idx).copied())
            .or_else(|| zombie_farm_actor_hunger(env, actor))
            .unwrap_or(0.0);
        let eat_date_hunger = if old_hunger <= 0.001 {
            zombie_farm_actor_eat_date(env, actor).and_then(|eat_date| {
                if eat_date == nil
                    || !env
                        .objc
                        .object_has_method(&env.mem, now, time_interval_since_date_selector)
                {
                    return None;
                }
                let elapsed_since_eat: f64 = msg_send_no_type_checking(
                    env,
                    (now, time_interval_since_date_selector, eat_date),
                );
                (elapsed_since_eat > 1.0 && elapsed_since_eat.is_finite())
                    .then(|| (elapsed_since_eat / 86_400.0).clamp(0.0, 1.0) as f32)
            })
        } else {
            None
        };
        let new_hunger = (old_hunger + hunger_delta)
            .max(eat_date_hunger.unwrap_or(0.0))
            .clamp(0.0, 1.0);
        if new_hunger > old_hunger + 0.001 {
            if !zombie_farm_set_actor_hunger(env, actor, new_hunger) {
                continue;
            }
            changed += 1;
        }
        max_hunger = max_hunger.max(new_hunger);
    }

    (zombies, changed, max_hunger)
}

fn zombie_farm_apply_offline_actor_hunger(env: &mut Environment) {
    static DISABLE_LOCAL_HUNGER: OnceLock<bool> = OnceLock::new();
    let disable_local_hunger = *DISABLE_LOCAL_HUNGER.get_or_init(|| {
        std::env::var("TOUCHHLE_ZF_DISABLE_LOCAL_HUNGER")
            .map(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(false)
    });

    if !zombie_farm_uses_playforge_bundle(env) || disable_local_hunger {
        return;
    }

    let mut zombies = 0u32;
    let mut changed = 0u32;
    let mut max_elapsed = 0.0f64;
    let mut max_hunger = 0.0f32;

    let Some(game_state) = zombie_farm_get_game_state(env) else {
        return;
    };
    let Some(save_date) = zombie_farm_game_state_save_date(env, game_state) else {
        return;
    };
    let now: id = msg_class![env; NSDate date];
    let Some(time_interval_since_date_selector) =
        env.objc.lookup_selector("timeIntervalSinceDate:")
    else {
        return;
    };
    if !env
        .objc
        .object_has_method(&env.mem, now, time_interval_since_date_selector)
    {
        return;
    }
    let elapsed_since_save: f64 =
        msg_send_no_type_checking(env, (now, time_interval_since_date_selector, save_date));
    if !elapsed_since_save.is_finite() {
        return;
    }

    let save_date_interval = zombie_farm_date_interval(env, save_date).unwrap_or(f64::NAN);
    let saved_actor_list = zombie_farm_get_actor_list(env);
    let saved_hungers = saved_actor_list
        .map(|actor_list| zombie_farm_zombie_hungers_in_list(env, actor_list))
        .unwrap_or_default();
    let max_saved_hunger = saved_hungers.iter().copied().fold(0.0f32, f32::max);
    let (save_date_zombies, eat_dates_near_save_date) = saved_actor_list
        .map(|actor_list| {
            zombie_farm_zombie_eat_dates_near(env, actor_list, save_date_interval, 2.0)
        })
        .unwrap_or((0, 0));
    let save_date_looks_like_old_eat_date_workaround =
        save_date_zombies > 0 && eat_dates_near_save_date * 2 >= save_date_zombies;
    let already_applied_seconds = if save_date_looks_like_old_eat_date_workaround {
        f64::from(max_saved_hunger) * 86_400.0
    } else {
        0.0
    };
    let hunger_delta =
        ((elapsed_since_save - already_applied_seconds).max(0.0) / 86_400.0).clamp(0.0, 1.0) as f32;
    if let Some(actor_list) = zombie_farm_get_actor_list(env) {
        let (list_zombies, list_changed, list_max_hunger) =
            zombie_farm_apply_offline_actor_hunger_to_list(
                env,
                actor_list,
                hunger_delta,
                now,
                time_interval_since_date_selector,
                None,
            );
        zombies += list_zombies;
        changed += list_changed;
        max_elapsed = max_elapsed.max(elapsed_since_save);
        max_hunger = max_hunger.max(list_max_hunger);
    }

    if let Some(actor_list) = zombie_farm_get_live_actor_list(env) {
        let (list_zombies, list_changed, list_max_hunger) =
            zombie_farm_apply_offline_actor_hunger_to_list(
                env,
                actor_list,
                hunger_delta,
                now,
                time_interval_since_date_selector,
                (!saved_hungers.is_empty()).then_some(saved_hungers.as_slice()),
            );
        zombies += list_zombies;
        changed += list_changed;
        max_elapsed = max_elapsed.max(elapsed_since_save);
        max_hunger = max_hunger.max(list_max_hunger);
    }

    let (sync_zombies, sync_changed, sync_max_hunger) = zombie_farm_sync_actor_hunger_lists(env);
    zombies += sync_zombies;
    changed += sync_changed;
    max_hunger = max_hunger.max(sync_max_hunger);

    zombie_farm_set_game_state_save_date(env, game_state, now);
    log_dbg!(
        "ZombieFarm status: local hunger advanced {}/{} zombie actor entries by {:.0}s since saveDate ({:.3} hunger), max hunger {:.3}",
        changed,
        zombies,
        max_elapsed,
        hunger_delta,
        max_hunger
    );
}

fn zombie_farm_prepare_local_server_date(env: &mut Environment, receiver: id, selector_name: &str) {
    if !matches!(selector_name, "getServerTime" | "handleResponse:forAction:") {
        return;
    }

    let regs = *env.cpu.regs();
    let gui_layer = if zombie_farm_object_class_name(env, receiver) == Some("ZFGuiLayer") {
        Some(receiver)
    } else {
        zombie_farm_get_gui_layer(env)
    };
    if let Some(gui_layer) = gui_layer {
        zombie_farm_set_gui_layer_server_date_to_now(env, gui_layer);
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_is_legacy_social_response(
    bundle_identifier: &str,
    bundle_version: &str,
    class_name: Option<&str>,
    selector_name: &str,
) -> bool {
    bundle_identifier == "com.playforge.ZFR.LZ54D2GT3D"
        && bundle_version == "1.0"
        && class_name == Some("SocialMenu")
        && selector_name == "handleResponse:forAction:"
}

fn zombie_farm_complete_legacy_social_response(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_is_legacy_social_response(
        env.bundle.bundle_identifier(),
        env.bundle.bundle_version(),
        zombie_farm_object_class_name(env, receiver),
        selector_name,
    ) {
        return false;
    }

    // ZFR's retired tag endpoint can still complete after the UI that issued
    // it is gone. The guest handler installs an SJLJ exception frame and
    // decodes the legacy binary response; later failures have been observed
    // unwinding through that expired frame during unrelated fight cleanup.
    // The only implemented action in this exact guest method is
    // "sendTagResult"; every other action exits without changing state but
    // still installs the same unsafe exception frame. Complete the entire
    // obsolete callback at the host boundary.
    // The public farm server is implemented by separate host-managed /v1
    // endpoints and does not use this legacy tag response, so this obsolete
    // callback is unsafe in both offline and public-online modes.
    env.cpu.regs_mut()[0] = 0;
    log!("ZombieFarm workaround: skipped legacy SocialMenu handleResponse:forAction: callback");
    true
}

fn zombie_farm_is_unsafe_legacy_gift_action(
    bundle_identifier: &str,
    bundle_version: &str,
    class_name: Option<&str>,
    selector_name: &str,
    table_exists: bool,
    table_is_attached_to_window: bool,
    public_friend_mode: bool,
) -> bool {
    bundle_identifier == "com.playforge.ZFR.LZ54D2GT3D"
        && bundle_version == "1.0"
        && class_name == Some("SocialTableViewGifts")
        && selector_name == "acceptGift"
        && (public_friend_mode || !table_exists || !table_is_attached_to_window)
}

fn zombie_farm_skip_unsafe_gift_action(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZFR.LZ54D2GT3D"
        || env.bundle.bundle_version() != "1.0"
        || zombie_farm_object_class_name(env, receiver) != Some("SocialTableViewGifts")
        || selector_name != "acceptGift"
    {
        return false;
    }

    let table_view = zombie_farm_read_object_ivar(env, receiver, "tableView").unwrap_or(nil);
    let table_is_attached_to_window = if table_view == nil {
        false
    } else {
        let regs = *env.cpu.regs();
        let window = zombie_farm_get_id_if_responds(env, table_view, "window").unwrap_or(nil);
        env.cpu.regs_mut().copy_from_slice(&regs);
        window != nil
    };

    let public_friend_mode = ns_url_connection::zombie_farm_http_base_url(env).is_some();
    if !zombie_farm_is_unsafe_legacy_gift_action(
        env.bundle.bundle_identifier(),
        env.bundle.bundle_version(),
        zombie_farm_object_class_name(env, receiver),
        selector_name,
        table_view != nil,
        table_is_attached_to_window,
        public_friend_mode,
    ) {
        return false;
    }

    // The legacy gifts controller can survive after its UIKit hierarchy has
    // been removed. A delayed alert/control action may then enter acceptGift
    // while the robot fight is being created. That method mutates two table
    // rows and has repeatedly been observed returning through stale SJLJ/ARM
    // continuations into SocialMenu::handleResponse. A visible gifts table is
    // still allowed to accept gifts in the original offline path. The public
    // friend API does not implement incoming gifts, so acceptGift is obsolete
    // there even if the old table still reports a non-nil window.
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm workaround: skipped unsafe [SocialTableViewGifts acceptGift] (table {:?}, public friend mode={})",
        table_view,
        public_friend_mode
    );
    true
}

fn zombie_farm_is_obsolete_potential_friends_response(
    bundle_identifier: &str,
    bundle_version: &str,
    class_name: Option<&str>,
    selector_name: &str,
) -> bool {
    bundle_identifier == "com.playforge.ZFR.LZ54D2GT3D"
        && bundle_version == "1.0"
        && class_name == Some("SocialTableViewFacebook")
        && selector_name == "handlePotentialFriendsResponse:"
}

fn zombie_farm_skip_obsolete_potential_friends_response(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !zombie_farm_is_obsolete_potential_friends_response(
        env.bundle.bundle_identifier(),
        env.bundle.bundle_version(),
        zombie_farm_object_class_name(env, receiver),
        selector_name,
    ) {
        return false;
    }

    // This callback parses BrainClient's retired binary potential-friends
    // response. ZFR can deliver a malformed/stale completion long after the
    // social controller has left the screen. It has been observed continuing
    // during a robot fight, nested inside SocialTableViewGifts::acceptGift, and
    // corrupting the ARM return chain to PC 0x4. The host-managed public friend
    // list is installed directly by getFriendsList/findFriends and does not use
    // this legacy Facebook response, so this callback is obsolete in both modes.
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm workaround: skipped obsolete SocialTableViewFacebook handlePotentialFriendsResponse:"
    );
    true
}

fn zombie_farm_complete_stale_tag_summary_dismiss(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZFR.LZ54D2GT3D"
        || env.bundle.bundle_version() != "1.0"
        || selector_name != "dismissMenu:"
        || zombie_farm_object_class_name(env, receiver) != Some("ZFTagSummary")
    {
        return false;
    }

    // The legacy tag UI can finish dismissing after the fight scene has
    // already replaced it, including while the public farm server is enabled.
    // Its animation path asks CCDirector for a struct return, then has been
    // observed entering free() with corrupted guest return addresses.
    // Abandoning that entire guest call also abandons the surrounding Cocos
    // scheduler pass, which prevents later zombies from being deployed.
    // Complete the UI's tiny final callback normally instead: it only posts
    // kZombieTagSummaryDoneNotification.
    let regs = *env.cpu.regs();
    let completed = env
        .objc
        .lookup_selector("dismissTimerCallback")
        .filter(|&selector| env.objc.object_has_method(&env.mem, receiver, selector))
        .map(|selector| {
            let _: () = msg_send_no_type_checking(env, (receiver, selector));
        })
        .is_some();
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[0] = 0;

    if completed {
        log!(
            "ZombieFarm workaround: completed stale ZFTagSummary dismissMenu: without its broken animation"
        );
    } else {
        log!(
            "ZombieFarm workaround: skipped stale ZFTagSummary dismissMenu: because its completion callback is unavailable"
        );
    }
    true
}

fn zombie_farm_complete_server_time_locally(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if selector_name != "getServerTime"
        || zombie_farm_object_class_name(env, receiver) != Some("ZFGuiLayer")
    {
        return false;
    }

    let regs = *env.cpu.regs();
    zombie_farm_set_gui_layer_server_date_to_now(env, receiver);
    let response = zombie_farm_local_time_response(env);
    let handled =
        zombie_farm_send_id_arg_if_responds(env, receiver, "handleTimeResponse:", response);
    release(env, response);

    if handled {
        zombie_farm_show_due_daily_reward_locally(env, receiver, "getServerTime");
        ZOMBIE_FARM_CHECKED_LOCAL_DAILY_EVENT.store(true, Ordering::Relaxed);
        log!("ZombieFarm status: completed getServerTime locally for daily rewards");
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
    env.cpu.regs_mut()[0] = 0;
    handled
}

fn zombie_farm_disable_legacy_status_check_for_public_online(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if selector_name != "objectForKey:"
        || zombie_farm_object_class_name(env, receiver) != Some("NSUserDefaults")
        || ns_url_connection::zombie_farm_http_base_url(env).is_none()
    {
        return false;
    }

    let key = id::from_bits(env.cpu.regs()[2]);
    if key == nil || ns_string::to_rust_string(env, key).as_ref() != "ZFStatusCheckDisabled" {
        return false;
    }

    // Zombie Farm already has an offline status-check path guarded by this
    // preference. It clears the transient status, updates the active farm, and
    // posts kActiveProfileStatusCheckDoneNotification without contacting the
    // retired Playforge profile-status endpoint. Keep the override in-memory
    // and scoped to the explicitly enabled public server mode.
    let disabled: id = msg_class![env; NSNumber numberWithBool:true];
    env.cpu.regs_mut()[0] = disabled.to_bits();

    static LOGGED: AtomicBool = AtomicBool::new(false);
    if !LOGGED.swap(true, Ordering::Relaxed) {
        log!("ZombieFarm public online: using the game's local active-profile status completion");
    }
    true
}

fn zombie_farm_apply_local_hunger_update(env: &mut Environment, receiver: id, selector_name: &str) {
    if !matches!(
        selector_name,
        "startUpChecksComplete" | "handleTimeResponse:"
    ) {
        return;
    }
    let regs = *env.cpu.regs();
    let gui_layer = if zombie_farm_object_class_name(env, receiver) == Some("ZFGuiLayer") {
        Some(receiver)
    } else {
        zombie_farm_get_gui_layer(env)
    };
    let is_gui_layer = gui_layer
        .map(|gui_layer| zombie_farm_set_gui_layer_server_date_to_now(env, gui_layer))
        .unwrap_or(false);
    if env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2" {
        log_dbg!("ZombieFarm2 workaround: skipping offline hunger update during startup");
        env.cpu.regs_mut().copy_from_slice(&regs);
        return;
    }
    let Some(apply_hunger_selector) = env.objc.lookup_selector("applyZombieHunger") else {
        zombie_farm_apply_offline_actor_hunger(env);
        env.cpu.regs_mut().copy_from_slice(&regs);
        return;
    };
    if let Some(gui_layer) = gui_layer {
        if is_gui_layer
            && zombie_farm_ensure_game_state_save_date(env)
            && !ZOMBIE_FARM_APPLIED_LOCAL_HUNGER.swap(true, Ordering::Relaxed)
            && env
                .objc
                .object_has_method(&env.mem, gui_layer, apply_hunger_selector)
        {
            log_dbg!("ZombieFarm status: applying offline zombie hunger update");
            let _: () = msg_send_no_type_checking(env, (gui_layer, apply_hunger_selector));
        }
    }
    zombie_farm_apply_offline_actor_hunger(env);
    env.cpu.regs_mut().copy_from_slice(&regs);
}

const ZOMBIE_FARM_SOCIAL_TUTORIAL_FLAGS: i32 = 0x1ff;

/// Mark every step of Zombie Farm's social tutorial as completed while the
/// experimental public-farm server is enabled.
///
/// Doing this during startup makes a brand-new local save usable before the
/// player first opens SocialMenu. Doing it again before `saveGame` ensures the
/// completed bits are serialized into saveGame.bin2 instead of being only an
/// in-memory UI workaround.
fn zombie_farm_complete_social_tutorial(env: &mut Environment, reason: &str) -> bool {
    if ns_url_connection::zombie_farm_http_base_url(env).is_none() {
        return false;
    }

    let regs = *env.cpu.regs();
    let game_state: id = msg_class![env; GameState gameState];
    let game_data: id = if game_state == nil {
        nil
    } else {
        msg![env; game_state zfGameData]
    };
    if game_data == nil {
        env.cpu.regs_mut().copy_from_slice(&regs);
        return false;
    }

    // SocialMenu consumes bits 0..=8 of gflags2, with 0x100 being the final
    // acknowledgement set by tutorialOkButtonPressed.
    let flags: i32 = msg![env; game_data gflags2];
    let completed_flags = flags | ZOMBIE_FARM_SOCIAL_TUTORIAL_FLAGS;
    if completed_flags != flags {
        let _: () = msg![env; game_data setGflags2:completed_flags];
        log!(
            "ZombieFarm public online: completed social tutorial in GameData during {reason} (gflags2 0x{flags:x} -> 0x{completed_flags:x})"
        );
    }

    env.cpu.regs_mut().copy_from_slice(&regs);
    true
}

fn zombie_farm_acknowledge_daily_reward_confirmation(env: &mut Environment, receiver: id) {
    // The first argument is the Cocos daily-window choice: true for Claim,
    // false for Wait. Only Claim enters the otherwise invisible UIKit
    // confirmation path.
    if env.cpu.regs()[2] == 0 || zombie_farm_object_class_name(env, receiver) != Some("ZFGuiLayer")
    {
        return;
    }

    let regs = *env.cpu.regs();
    let game_state: id = msg_class![env; GameState gameState];
    let game_data: id = if game_state == nil {
        nil
    } else {
        msg![env; game_state zfGameData]
    };
    if game_data != nil {
        const DAILY_REWARD_CONFIRMATION_ACKNOWLEDGED: i32 = 0x2000_0000;
        let flags: i32 = msg![env; game_data gflags];
        if flags & DAILY_REWARD_CONFIRMATION_ACKNOWLEDGED == 0 {
            let updated_flags = flags | DAILY_REWARD_CONFIRMATION_ACKNOWLEDGED;
            let _: () = msg![env; game_data setGflags:updated_flags];
            log!("ZombieFarm daily reward: acknowledged invisible confirmation before first Claim");
        }
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_check_local_daily_event(env: &mut Environment, receiver: id, selector_name: &str) {
    if !zombie_farm_uses_playforge_bundle(env)
        || !matches!(selector_name, "statusCheckDone" | "startUpChecksComplete")
        || ZOMBIE_FARM_CHECKED_LOCAL_DAILY_EVENT.load(Ordering::Relaxed)
    {
        return;
    }

    let regs = *env.cpu.regs();
    let gui_layer = if zombie_farm_object_class_name(env, receiver) == Some("ZFGuiLayer") {
        Some(receiver)
    } else {
        zombie_farm_get_gui_layer(env)
    };

    let Some(gui_layer) = gui_layer else {
        env.cpu.regs_mut().copy_from_slice(&regs);
        return;
    };

    zombie_farm_set_gui_layer_server_date_to_now(env, gui_layer);
    let time_response = zombie_farm_local_time_response(env);
    ZOMBIE_FARM_CHECKED_LOCAL_DAILY_EVENT.store(true, Ordering::Relaxed);
    if zombie_farm_send_id_arg_if_responds(env, gui_layer, "handleTimeResponse:", time_response) {
        zombie_farm_show_due_daily_reward_locally(env, gui_layer, selector_name);
        log!(
            "ZombieFarm status: completed local daily event time response after {}",
            selector_name
        );
    } else {
        ZOMBIE_FARM_CHECKED_LOCAL_DAILY_EVENT.store(false, Ordering::Relaxed);
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_show_due_daily_reward_locally(
    env: &mut Environment,
    gui_layer: id,
    reason: &str,
) -> bool {
    if zombie_farm_object_class_name(env, gui_layer) != Some("ZFGuiLayer") {
        return false;
    }

    let regs = *env.cpu.regs();
    let game_state: id = msg_class![env; GameState gameState];
    let game_data: id = if game_state == nil {
        nil
    } else {
        msg![env; game_state zfGameData]
    };
    if game_data == nil {
        env.cpu.regs_mut().copy_from_slice(&regs);
        return false;
    }

    let display_date: id = msg![env; game_data dailyBonusRewardDisplayDate];
    let now: id = msg_class![env; NSDate date];
    let now_seconds = zombie_farm_date_unix_seconds(env, now);
    let display_seconds = zombie_farm_date_unix_seconds(env, display_date);
    let now_day =
        now_seconds.and_then(|seconds| zombie_farm_calendar_day_in_timezone(seconds, &Local));
    let display_day = display_seconds
        .and_then(|seconds| zombie_farm_legacy_compatible_day_in_timezone(seconds, &Local));
    let reward_is_due = display_date == nil
        || now_day
            .zip(display_day)
            .map(|(now, last)| now > last)
            .unwrap_or(false);

    let shown =
        reward_is_due && zombie_farm_send_noarg_if_responds(env, gui_layer, "showDailyEvents");
    if shown {
        log!(
            "ZombieFarm daily reward: invoked showDailyEvents after {} (local day {:?}, previous local day {:?})",
            reason,
            now_day,
            display_day,
        );
    } else if zombie_farm_daily_trace_enabled() {
        log!(
            "ZombieFarm daily trace: reward not shown after {} (displayDate={:?}, localDay={:?}, previousLocalDay={:?}, due={})",
            reason,
            display_date,
            now_day,
            display_day,
            reward_is_due,
        );
    }

    env.cpu.regs_mut().copy_from_slice(&regs);
    shown
}

const ZOMBIE_FARM_SECONDS_PER_DAY: f64 = 86_400.0;
const ZOMBIE_FARM_UTC_MIDNIGHT_TOLERANCE_SECONDS: f64 = 0.001;

fn zombie_farm_date_unix_seconds(env: &Environment, date: id) -> Option<f64> {
    ns_date::debug_time_interval(env, date)
        .map(|seconds| seconds + SECS_FROM_UNIX_TO_APPLE_EPOCHS as f64)
}

fn zombie_farm_utc_datetime(unix_seconds: f64) -> Option<DateTime<Utc>> {
    if !unix_seconds.is_finite() {
        return None;
    }

    let whole_seconds = unix_seconds.floor();
    if whole_seconds < i64::MIN as f64 || whole_seconds > i64::MAX as f64 {
        return None;
    }

    DateTime::<Utc>::from_timestamp(whole_seconds as i64, 0)
}

fn zombie_farm_calendar_day_in_timezone<Tz: TimeZone>(
    unix_seconds: f64,
    time_zone: &Tz,
) -> Option<NaiveDate> {
    Some(
        zombie_farm_utc_datetime(unix_seconds)?
            .with_timezone(time_zone)
            .date_naive(),
    )
}

fn zombie_farm_was_legacy_utc_midnight(unix_seconds: f64) -> bool {
    let seconds_since_midnight = unix_seconds.rem_euclid(ZOMBIE_FARM_SECONDS_PER_DAY);
    seconds_since_midnight <= ZOMBIE_FARM_UTC_MIDNIGHT_TOLERANCE_SECONDS
        || ZOMBIE_FARM_SECONDS_PER_DAY - seconds_since_midnight
            <= ZOMBIE_FARM_UTC_MIDNIGHT_TOLERANCE_SECONDS
}

fn zombie_farm_legacy_compatible_day_in_timezone<Tz: TimeZone>(
    unix_seconds: f64,
    time_zone: &Tz,
) -> Option<NaiveDate> {
    let utc_date = zombie_farm_utc_datetime(unix_seconds)?;
    if zombie_farm_was_legacy_utc_midnight(unix_seconds) {
        // Old ZFR saves stored the intended calendar date as midnight UTC.
        // Preserve that date label when migrating to a host-local midnight.
        Some(utc_date.date_naive())
    } else {
        Some(utc_date.with_timezone(time_zone).date_naive())
    }
}

fn zombie_farm_first_valid_instant_for_day<Tz: TimeZone>(
    day: NaiveDate,
    time_zone: &Tz,
) -> Option<f64> {
    for minute_of_day in 0..(24 * 60) {
        let hour = minute_of_day / 60;
        let minute = minute_of_day % 60;
        let Some(local_time) = day.and_hms_opt(hour, minute, 0) else {
            continue;
        };
        let date_time = match time_zone.from_local_datetime(&local_time) {
            LocalResult::Single(value) => value,
            LocalResult::Ambiguous(first, second) => {
                if first.timestamp() <= second.timestamp() {
                    first
                } else {
                    second
                }
            }
            LocalResult::None => continue,
        };
        return Some(date_time.timestamp() as f64);
    }

    None
}

fn zombie_farm_start_of_local_day_in_timezone<Tz: TimeZone>(
    unix_seconds: f64,
    time_zone: &Tz,
) -> Option<(NaiveDate, f64, bool)> {
    let migrated_legacy_utc_midnight = zombie_farm_was_legacy_utc_midnight(unix_seconds);
    let day = zombie_farm_legacy_compatible_day_in_timezone(unix_seconds, time_zone)?;
    let start_seconds = zombie_farm_first_valid_instant_for_day(day, time_zone)?;
    Some((day, start_seconds, migrated_legacy_utc_midnight))
}

fn zombie_farm_return_local_beginning_of_day(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if env.bundle.bundle_identifier() != "com.playforge.ZFR.LZ54D2GT3D"
        || env.bundle.bundle_version() != "1.0"
        || selector_name != "getBeginningOfTheDayFromDate:"
        || zombie_farm_object_class_name(env, receiver) != Some("GameState")
    {
        return false;
    }

    let date = id::from_bits(env.cpu.regs()[2]);
    let Some(unix_seconds) = zombie_farm_date_unix_seconds(env, date) else {
        return false;
    };
    let Some((day, start_seconds, migrated_legacy_utc_midnight)) =
        zombie_farm_start_of_local_day_in_timezone(unix_seconds, &Local)
    else {
        return false;
    };

    let result: id = msg_class![env; NSDate dateWithTimeIntervalSince1970:start_seconds];
    env.cpu.regs_mut()[0] = result.to_bits();

    if zombie_farm_daily_trace_enabled() {
        log!(
            "ZombieFarm daily trace: returned host-local beginning of day {} ({:.0} Unix seconds, migrated legacy UTC midnight={})",
            day,
            start_seconds,
            migrated_legacy_utc_midnight,
        );
    }
    true
}

fn zombie_farm_trace_daily_reward_gate(env: &mut Environment, gui_layer: id) {
    if !zombie_farm_daily_trace_enabled()
        || zombie_farm_object_class_name(env, gui_layer) != Some("ZFGuiLayer")
    {
        return;
    }

    let regs = *env.cpu.regs();
    let game_state: id = msg_class![env; GameState gameState];
    let game_data: id = if game_state == nil {
        nil
    } else {
        msg![env; game_state zfGameData]
    };
    let display_date: id = if game_data == nil {
        nil
    } else {
        msg![env; game_data dailyBonusRewardDisplayDate]
    };
    let day_count: i32 = if game_data == nil {
        0
    } else {
        msg![env; game_data dailyBonusRewardDayCount]
    };
    let server_date = zombie_farm_read_object_ivar(env, gui_layer, "serverDate").unwrap_or(nil);
    let daily_reward_window =
        zombie_farm_read_object_ivar(env, gui_layer, "dailyRewardWindow").unwrap_or(nil);
    let server_seconds = ns_date::debug_time_interval(env, server_date);
    let display_seconds = ns_date::debug_time_interval(env, display_date);
    let elapsed_seconds = server_seconds
        .zip(display_seconds)
        .map(|(now, last)| now - last);

    log!(
        "ZombieFarm daily trace: gate serverDate={:?} ({:?}), displayDate={:?} ({:?}), rawElapsedSeconds={:?}, dayCount={}, dailyRewardWindow={:?}",
        server_date,
        server_seconds,
        display_date,
        display_seconds,
        elapsed_seconds,
        day_count,
        daily_reward_window,
    );
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_prepare_local_hunger_update(env: &mut Environment, selector_name: &str) {
    if !matches!(
        selector_name,
        "openMenu"
            | "openMenuThroughMausoleum"
            | "displayCurrentZombie"
            | "updateSelectedZombieInfo"
            | "displayHunger"
            | "table:cellTouched:"
            | "saveGame"
            | "startInvasion:"
            | "startInvasion:checkHunger:"
            | "startInvasionWithDictionary:checkHunger:"
            | "invadeButtonTapped:"
            | "switchToFightScene"
    ) {
        return;
    }

    let regs = *env.cpu.regs();
    zombie_farm_ensure_game_state_save_date(env);
    zombie_farm_apply_offline_actor_hunger(env);
    zombie_farm_force_all_zombie_hunger(env, selector_name);
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn zombie_farm_md5sum_override(env: &mut Environment, selector_name: &str) -> Option<id> {
    if selector_name != "md5sum:"
        || !(env
            .bundle
            .bundle_identifier()
            .starts_with("com.playforge.ZombieFarm")
            || env
                .bundle
                .bundle_identifier()
                .starts_with("com.playforge.ZFR"))
    {
        return None;
    }

    let path = id::from_bits(env.cpu.regs()[2]);
    if path == nil {
        return None;
    }

    let class = ObjC::read_isa(path, &env.mem);
    if class == nil {
        return None;
    }
    let string_class = env.objc.get_known_class("NSString", &mut env.mem);
    if !env.objc.class_is_subclass_of(class, string_class) {
        return None;
    }

    let path = ns_string::to_rust_string(env, path).to_string();
    let digest = ns_property_list_serialization::zombie_farm_expected_plist_md5_hex(env, &path)?;
    log_dbg!(
        "ZombieFarm: using digest.plist MD5 for {}: {}",
        path,
        digest
    );
    let digest = ns_string::from_rust_string(env, digest);
    Some(autorelease(env, digest))
}

pub(super) fn trace_zombie_farm_layout_stret_return(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    stret: MutVoidPtr,
) {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || stret.is_null()
    {
        return;
    }
    if receiver == nil {
        return;
    }
    let selector_name = selector.as_str(&env.mem);
    let class = ObjC::read_isa(receiver, &env.mem);
    if class == nil {
        return;
    }
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return;
    };
    if !trace_zombie_farm_layout_message(class_name, selector_name) {
        return;
    }
    match selector_name {
        "cellSize" | "viewSize" | "contentSize" => {
            let size: CGSize = env.mem.read(stret.cast());
            crate::zombie_farm_debug::record_table_size_return(
                receiver,
                class_name,
                selector_name,
                size,
            );
            if trace_zombie_farm_layout_to_console(selector_name) {
                log_dbg!(
                    "ZombieFarm trace: [{} {}] receiver {:?} return size={}",
                    class_name,
                    selector_name,
                    receiver,
                    size
                );
            }
        }
        "position" | "contentOffset" => {
            let point: CGPoint = env.mem.read(stret.cast());
            crate::zombie_farm_debug::record_table_point_return(
                receiver,
                class_name,
                selector_name,
                point,
            );
            if trace_zombie_farm_layout_to_console(selector_name) {
                log_dbg!(
                    "ZombieFarm trace: [{} {}] receiver {:?} return point={}",
                    class_name,
                    selector_name,
                    receiver,
                    point
                );
            }
        }
        _ => {}
    }
}

pub(super) fn trace_zombie_farm_layout_normal_return(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
) {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || receiver == nil
    {
        return;
    }
    let selector_name = selector.as_str(&env.mem);
    let class = ObjC::read_isa(receiver, &env.mem);
    if class == nil {
        return;
    }
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return;
    };
    if !trace_zombie_farm_layout_message(class_name, selector_name) {
        return;
    }
    match selector_name {
        "direction" | "_indexFromOffset:" => {
            crate::zombie_farm_debug::record_table_value_return(
                receiver,
                class_name,
                selector_name,
                env.cpu.regs()[0],
            );
            log_dbg!(
                "ZombieFarm trace: [{} {}] receiver {:?} return value={}",
                class_name,
                selector_name,
                receiver,
                env.cpu.regs()[0]
            );
        }
        "cellWithIndex:" | "table:cellAtIndex:" | "cellClassForTable:" | "dequeueCell" => {
            let object = id::from_bits(env.cpu.regs()[0]);
            let object_class_name = if object == nil {
                None
            } else {
                let object_class = ObjC::read_isa(object, &env.mem);
                if object_class == nil {
                    None
                } else {
                    env.objc.try_get_class_name(object_class)
                }
            };
            crate::zombie_farm_debug::record_table_object_return(
                receiver,
                class_name,
                selector_name,
                object,
                object_class_name,
            );
            if trace_zombie_farm_layout_to_console(selector_name) {
                log_dbg!(
                    "ZombieFarm trace: [{} {}] receiver {:?} return object {:?} ({:?})",
                    class_name,
                    selector_name,
                    receiver,
                    object,
                    object_class_name
                );
            }
        }
        _ => {}
    }
}

pub(super) fn trace_zombie_farm_status_normal_return(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
) {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || receiver == nil
    {
        return;
    }
    let selector_name = selector.as_str(&env.mem);
    let class = ObjC::read_isa(receiver, &env.mem);
    if class == nil {
        return;
    }
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return;
    };
    if !trace_zombie_farm_status_message(class_name, selector_name) {
        return;
    }
    match selector_name {
        "timeIntervalSinceDate:"
        | "timeIntervalSinceNow"
        | "timeIntervalSince1970"
        | "timeIntervalSinceReferenceDate" => {
            let mut bytes = [0u8; 8];
            bytes[0..4].copy_from_slice(&env.cpu.regs()[0].to_le_bytes());
            bytes[4..8].copy_from_slice(&env.cpu.regs()[1].to_le_bytes());
            let value = f64::from_bits(u64::from_le_bytes(bytes));
            log!(
                "ZombieFarm status: [{} {}] receiver {:?} return {:.3}",
                class_name,
                selector_name,
                receiver,
                value
            );
        }
        "saveDate"
        | "addTimeInterval:"
        | "getBeginningOfTheDayFromDate:"
        | "dailyRewardWindow"
        | "dailyBonusRewardDisplayDate"
        | "dailyBonusRewardRedeemedDate" => {
            log!(
                "ZombieFarm status: [{} {}] receiver {:?} return object {:?}",
                class_name,
                selector_name,
                receiver,
                id::from_bits(env.cpu.regs()[0])
            );
        }
        "dailyBonusRewardDayCount"
        | "goldAmountForDayCount:"
        | "brainChanceForDayCount:"
        | "canShowDailySalesmanOffer" => {
            log!(
                "ZombieFarm status: [{} {}] receiver {:?} return value={}",
                class_name,
                selector_name,
                receiver,
                env.cpu.regs()[0]
            );
        }
        _ if zombie_farm_status_trace_enabled() => {
            let value_id = id::from_bits(env.cpu.regs()[0]);
            log!(
                "ZombieFarm status: [{} {}] receiver {:?} return r0=0x{:x} ({:?}) class {:?}",
                class_name,
                selector_name,
                receiver,
                env.cpu.regs()[0],
                value_id,
                zombie_farm_object_class_name(env, value_id),
            );
        }
        _ => {}
    }
}

pub(super) fn trace_zombie_farm_quest_normal_return(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
) {
    if !zombie_farm_uses_playforge_bundle(env)
        || !zombie_farm_quest_trace_enabled()
        || receiver == nil
    {
        return;
    }
    let selector_name = selector.as_str(&env.mem);
    let class = ObjC::read_isa(receiver, &env.mem);
    if class == nil {
        return;
    }
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return;
    };
    if !trace_zombie_farm_quest_message(class_name, selector_name) {
        return;
    }

    log!(
        "ZombieFarm quest: [{} {}] receiver {:?} return r0=0x{:x} ({:?})",
        class_name,
        selector_name,
        receiver,
        env.cpu.regs()[0],
        id::from_bits(env.cpu.regs()[0]),
    );
}

fn zombie_farm_disable_cctable_cell_reuse(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if selector_name != "dequeueCell"
        || receiver == nil
        || !env
            .bundle
            .bundle_identifier()
            .starts_with("com.playforge.Z")
    {
        return false;
    }

    let class = ObjC::read_isa(receiver, &env.mem);
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    let class_name = class_name.to_string();
    if !class_name.contains("TableView") {
        return false;
    }

    crate::zombie_farm_debug::record_table_object_return(
        receiver,
        &class_name,
        selector_name,
        nil,
        None,
    );
    crate::zombie_farm_debug::record_layout_event(format!(
        "[0x{:x} {} dequeueCell] forced nil; Zombie Farm table reuse disabled",
        receiver.to_bits(),
        class_name
    ));
    env.cpu.regs_mut()[0] = nil.to_bits();
    true
}

pub(super) fn zombie_farm_cell_content_size_override(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    stret: MutVoidPtr,
) -> bool {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || receiver == nil
        || stret.is_null()
        || selector.as_str(&env.mem) != "contentSize"
    {
        return false;
    }

    let class = ObjC::read_isa(receiver, &env.mem);
    if class == nil {
        return false;
    }

    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    if !(class_name.starts_with("ZF") && class_name.ends_with("Cell")) {
        return false;
    }
    let class_name = class_name.to_string();

    let Some(cell_size) = zombie_farm_cell_size(env, receiver) else {
        return false;
    };
    env.mem.write(stret.cast(), cell_size);
    log_dbg!(
        "ZombieFarm workaround: [{} contentSize] -> class cellSize {}",
        class_name,
        cell_size
    );
    true
}

const ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN: u32 = 0x0023_2090;

fn zombie_farm_is_tag_summary_win_size_call(
    bundle_identifier: &str,
    bundle_version: &str,
    receiver_class_name: Option<&str>,
    selector_name: &str,
    guest_lr: u32,
) -> bool {
    bundle_identifier == "com.playforge.ZFR.LZ54D2GT3D"
        && bundle_version == "1.0"
        && matches!(
            receiver_class_name,
            Some("CCDirector" | "CCFastDirector" | "CCThreadedFastDirector")
        )
        && selector_name == "winSize"
        && guest_lr == ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN
}

fn zombie_farm_cocos_win_size(device_orientation: u32, surface_size: CGSize) -> CGSize {
    if matches!(device_orientation, 3 | 4) {
        CGSize {
            width: surface_size.height,
            height: surface_size.width,
        }
    } else {
        surface_size
    }
}

pub(super) fn zombie_farm_tag_summary_win_size_override(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    stret: MutVoidPtr,
) -> bool {
    if receiver == nil || stret.is_null() {
        return false;
    }

    let selector_name = selector.as_str(&env.mem);
    let receiver_class_name = zombie_farm_object_class_name(env, receiver);
    if !zombie_farm_is_tag_summary_win_size_call(
        env.bundle.bundle_identifier(),
        env.bundle.bundle_version(),
        receiver_class_name,
        selector_name,
        env.cpu.regs()[Cpu::LR],
    ) {
        return false;
    }

    // ZFR's -[ZFTagSummary dismissMenu:] calls [CCDirector winSize] through
    // objc_msgSend_stret at 0x0023208c. On this one legacy path the return from
    // the host dispatch stub has intermittently resumed the ARM caller in
    // Thumb mode, eventually wandering into free() and stale social callbacks.
    // The guest winSize implementation only reads these two CCDirector ivars,
    // swapping the surface dimensions for landscape orientations. Reproduce
    // that result directly so no guest call/return boundary is involved.
    let Some(device_orientation_ivar) =
        env.objc
            .object_lookup_ivar(&env.mem, receiver, &"deviceOrientation_".to_string())
    else {
        return false;
    };
    let Some(surface_size_ivar) =
        env.objc
            .object_lookup_ivar(&env.mem, receiver, &"surfaceSize_".to_string())
    else {
        return false;
    };
    let device_orientation: u32 = env.mem.read(device_orientation_ivar.cast());
    let surface_size: CGSize = env.mem.read(surface_size_ivar.cast());
    let win_size = zombie_farm_cocos_win_size(device_orientation, surface_size);
    env.mem.write(stret.cast(), win_size);
    log!(
        "ZombieFarm workaround: returned CCDirector winSize {} directly for ZFTagSummary dismissMenu:",
        win_size
    );
    true
}

pub(super) fn zombie_farm_prepare_cctable_cell(env: &mut Environment, receiver: id, selector: SEL) {
    let is_set_index = selector.as_str(&env.mem) == "_setIndex:forCell:";
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || !is_set_index
    {
        return;
    }

    let table_class = ObjC::read_isa(receiver, &env.mem);
    let Some(table_class_name) = env.objc.try_get_class_name(table_class) else {
        return;
    };
    let table_class_name = table_class_name.to_string();
    if !table_class_name.contains("TableView") {
        return;
    }

    let regs = env.cpu.regs();
    let index = regs[2];
    let cell = id::from_bits(regs[3]);
    if cell == nil {
        return;
    }

    let cell_class = ObjC::read_isa(cell, &env.mem);
    if cell_class == nil {
        return;
    }
    let Some(cell_class_name) = env.objc.try_get_class_name(cell_class) else {
        return;
    };
    let cell_class_name = cell_class_name.to_string();

    let Some(set_content_size_selector) = env.objc.lookup_selector("setContentSize:") else {
        return;
    };

    let Some(cell_size) = zombie_farm_cell_size(env, cell) else {
        return;
    };

    let mut synced_objects = Vec::new();
    zombie_farm_sync_cell_container_size(
        env,
        cell,
        set_content_size_selector,
        cell_size,
        &mut synced_objects,
    );

    let mut primary_node = nil;
    for selector_name in ["node", "cellLayer", "cellLayer2"] {
        let Some(container) = zombie_farm_get_id_if_responds(env, cell, selector_name) else {
            continue;
        };
        if container == nil {
            continue;
        }
        if selector_name == "node" {
            primary_node = container;
        }
        if synced_objects
            .iter()
            .copied()
            .any(|bits| bits == container.to_bits())
        {
            continue;
        }
        zombie_farm_sync_cell_container_size(
            env,
            container,
            set_content_size_selector,
            cell_size,
            &mut synced_objects,
        );
        if selector_name != "node" {
            zombie_farm_reset_cell_container_position(env, container);
        }
    }

    log_dbg!(
        "ZombieFarm workaround: prepared {} index {} cell {:?} node {:?} contentSize={} synced={:?}",
        cell_class_name,
        index,
        cell,
        primary_node,
        cell_size
        ,
        synced_objects
    );
}

fn zombie_farm_sync_cell_container_size(
    env: &mut Environment,
    object: id,
    set_content_size_selector: SEL,
    cell_size: CGSize,
    synced_objects: &mut Vec<u32>,
) {
    if object == nil {
        return;
    }
    let object_class = ObjC::read_isa(object, &env.mem);
    if object_class == nil
        || !env
            .objc
            .object_has_method(&env.mem, object_class, set_content_size_selector)
    {
        return;
    }
    let _: () = msg_send_no_type_checking(env, (object, set_content_size_selector, cell_size));
    synced_objects.push(object.to_bits());
}

fn zombie_farm_reset_cell_container_position(env: &mut Environment, object: id) {
    if object == nil {
        return;
    }
    let Some(position_selector) = env.objc.lookup_selector("position") else {
        return;
    };
    let Some(set_position_selector) = env.objc.lookup_selector("setPosition:") else {
        return;
    };
    if !env
        .objc
        .object_has_method(&env.mem, object, position_selector)
        || !env
            .objc
            .object_has_method(&env.mem, object, set_position_selector)
    {
        return;
    }

    let position: CGPoint = msg_send_no_type_checking(env, (object, position_selector));
    if position.x.abs() <= 0.5 && position.y.abs() <= 0.5 {
        return;
    }

    let _: () = msg_send_no_type_checking(env, (object, set_position_selector, CGPoint::default()));
}

fn zombie_farm_cell_size(env: &mut Environment, cell: id) -> Option<CGSize> {
    if cell == nil {
        return None;
    }
    let cell_size_selector = env.objc.lookup_selector("cellSize")?;

    if env
        .objc
        .object_has_method(&env.mem, cell, cell_size_selector)
    {
        return Some(msg_send_no_type_checking(env, (cell, cell_size_selector)));
    }

    let cell_class = ObjC::read_isa(cell, &env.mem);
    if cell_class != nil
        && env
            .objc
            .object_has_method(&env.mem, cell_class, cell_size_selector)
    {
        return Some(msg_send_no_type_checking(
            env,
            (cell_class, cell_size_selector),
        ));
    }

    None
}

fn zombie_farm_relayout_actor_attachments(_env: &mut Environment, _cell: id) -> bool {
    false
}

fn zombie_farm_log_reuse_relayout_candidates(env: &mut Environment, cell: id) {
    zombie_farm_log_class_selectors_once(env, cell, "zombie-cell-reuse");

    let actor = zombie_farm_find_cell_zombie_actor(env, cell);
    let Some(actor) = actor else {
        return;
    };
    zombie_farm_log_class_selectors_once(env, actor, "zombie-cell-reuse-actor");

    let Some(attachments) = zombie_farm_read_object_ivar(env, actor, "attachments") else {
        return;
    };
    let Some(count) = zombie_farm_get_array_count(env, attachments) else {
        return;
    };
    for idx in 0..count.min(8) {
        let Some(attachment) = zombie_farm_get_array_object_at_index(env, attachments, idx) else {
            continue;
        };
        if zombie_farm_object_class_name(env, attachment) == Some("ActorAttachment") {
            zombie_farm_log_class_selectors_once(env, attachment, "zombie-cell-reuse-attachment");
            break;
        }
    }
}

fn zombie_farm_skip_redundant_zombie_cell_rebuild(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.Z")
        || receiver == nil
    {
        return false;
    }

    if selector_name == "dealloc" {
        zombie_farm_clear_zombie_cell_assignment(receiver);
        return false;
    }
    if selector_name != "setZombie:" {
        return false;
    }

    let class = ObjC::read_isa(receiver, &env.mem);
    let Some(class_name) = env.objc.try_get_class_name(class) else {
        return false;
    };
    let class_name = class_name.to_string();
    if !zombie_farm_is_zombie_cell_class_name(&class_name) {
        return false;
    }

    let zombie = id::from_bits(env.cpu.regs()[2]);
    if zombie == nil {
        return false;
    }

    let current_visual = zombie_farm_get_id_if_responds(env, receiver, "cellLayer")
        .or_else(|| zombie_farm_get_id_if_responds(env, receiver, "node"));
    let Some(current_visual) = current_visual else {
        return false;
    };
    if current_visual == nil {
        return false;
    }

    let receiver_bits = receiver.to_bits();
    let zombie_key = zombie_farm_zombie_identity_key(env, zombie);
    let state = zombie_farm_zombie_cell_state().lock().unwrap();
    let cached_same =
        state.last_zombie_by_cell.get(&receiver_bits).copied() == Some(zombie.to_bits());
    let cached_same_key = zombie_key
        .as_ref()
        .is_some_and(|key| state.last_zombie_key_by_cell.get(&receiver_bits) == Some(key));
    drop(state);
    let current_same = {
        let current_zombie = zombie_farm_get_id_if_responds(env, receiver, "zombie")
            .or_else(|| zombie_farm_get_id_if_responds(env, receiver, "currentZombie"));
        current_zombie.is_some_and(|current| current == zombie)
    };
    if !cached_same && !cached_same_key && !current_same {
        return false;
    }

    zombie_farm_log_reuse_relayout_candidates(env, receiver);
    let relaid_out = zombie_farm_relayout_actor_attachments(env, receiver);

    crate::zombie_farm_debug::record_layout_event(format!(
        "[0x{:x} {} setZombie:] skipped redundant rebuild for zombie {:?} key={:?} visual {:?} relayout={}",
        receiver_bits, class_name, zombie, zombie_key, current_visual, relaid_out
    ));
    env.cpu.regs_mut()[0] = 0;
    true
}

fn zombie_farm_override_active_player_display_name(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if selector_name != "displayName"
        || zombie_farm_object_class_name(env, receiver) != Some("PlayerProfile")
    {
        return false;
    }

    static PLAYER_NAME: OnceLock<Option<String>> = OnceLock::new();
    let Some(player_name) = PLAYER_NAME
        .get_or_init(|| {
            std::env::var("TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME")
                .ok()
                .filter(|name| !name.is_empty())
        })
        .as_deref()
    else {
        return false;
    };

    let active_player: id = msg_class![env; PlayerProfileManager getActivePlayer];
    if active_player == nil || receiver != active_player {
        return false;
    }

    let player_name = ns_string::from_rust_string(env, player_name.to_string());
    env.cpu.regs_mut()[0] = autorelease(env, player_name).to_bits();

    static LOGGED: AtomicBool = AtomicBool::new(false);
    if !LOGGED.swap(true, Ordering::Relaxed) {
        log!(
            "ZombieFarm: overriding active player displayName from TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME"
        );
    }
    true
}

fn zombie_farm_override_public_game_center_profile(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !matches!(
        selector_name,
        "playerProfileType" | "playerGameCenterID" | "gameCenterAlias" | "playforgeAlias"
    ) || zombie_farm_object_class_name(env, receiver) != Some("PlayerProfile")
        || ns_url_connection::zombie_farm_http_base_url(env).is_none()
    {
        return false;
    }

    let active_player: id = msg_class![env; PlayerProfileManager getActivePlayer];
    if active_player == nil || receiver != active_player {
        return false;
    }

    if selector_name == "playerProfileType" {
        // Zombie Farm 1.0 uses 2 for a Game Center-backed PlayerProfile and
        // refuses to open the social menu for any other profile type.
        env.cpu.regs_mut()[0] = 2;
        static LOGGED: AtomicBool = AtomicBool::new(false);
        if !LOGGED.swap(true, Ordering::Relaxed) {
            log!("ZombieFarm public identity mapped to active Game Center profile");
        }
        return true;
    }

    let local_player: id = msg_class![env; GKLocalPlayer localPlayer];
    if local_player == nil {
        return false;
    }
    let value: id = if selector_name == "playerGameCenterID" {
        msg![env; local_player playerID]
    } else {
        msg![env; local_player alias]
    };
    if value == nil {
        return false;
    }
    env.cpu.regs_mut()[0] = value.to_bits();
    true
}

#[derive(serde::Deserialize)]
struct ZombieFarmPublicFriendList {
    farms: Vec<ZombieFarmPublicFriend>,
}

#[derive(serde::Deserialize)]
struct ZombieFarmPublicFriend {
    public_id: String,
    username: String,
}

#[derive(Clone)]
struct ZombieFarmPublicFriendIdentity {
    public_id: String,
    username: String,
}

fn zombie_farm_public_friend_ids() -> &'static Mutex<HashMap<i32, ZombieFarmPublicFriendIdentity>> {
    static IDS: OnceLock<Mutex<HashMap<i32, ZombieFarmPublicFriendIdentity>>> = OnceLock::new();
    IDS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn zombie_farm_public_friend_numeric_id(public_id: &str, used: &HashSet<i32>) -> i32 {
    let digest = Sha256::digest(public_id.as_bytes());
    let mut candidate =
        (u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]) & 0x7fff_ffff) as i32;
    if candidate == 0 {
        candidate = 1;
    }
    while candidate == 1_450_573 || used.contains(&candidate) {
        candidate = if candidate == i32::MAX {
            1
        } else {
            candidate + 1
        };
    }
    candidate
}

fn zombie_farm_load_public_friend_list(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    let receiver_class = zombie_farm_object_class_name(env, receiver);
    let from_social_menu = receiver_class == Some("SocialMenu") && selector_name == "findFriends";
    let friends_table = match (receiver_class, selector_name) {
        (Some("SocialTableViewNeighbors"), "getFriendsList" | "findFriends:") => receiver,
        (Some("SocialMenu"), "findFriends") => {
            let table: id = msg![env; receiver friendsTable];
            if table == nil
                || zombie_farm_object_class_name(env, table) != Some("SocialTableViewNeighbors")
            {
                return false;
            }
            table
        }
        _ => return false,
    };
    let Some(base_url) = ns_url_connection::zombie_farm_http_base_url(env) else {
        return false;
    };

    let local_player: id = msg_class![env; GKLocalPlayer localPlayer];
    let local_id = if local_player == nil {
        String::new()
    } else {
        let value: id = msg![env; local_player playerID];
        if value == nil {
            String::new()
        } else {
            ns_string::to_rust_string(env, value).into_owned()
        }
    };
    let url = format!(
        "{}/v1/farms?exclude={}&limit=200",
        base_url,
        zombie_farm_percent_encode(&local_id)
    );
    let friends = match ns_url_connection::zombie_farm_http_request("GET", &url, &[], Vec::new()) {
        Ok(response) if response.status == 200 => {
            match serde_json::from_slice::<ZombieFarmPublicFriendList>(&response.body) {
                Ok(list) => list.farms,
                Err(error) => {
                    log!("ZombieFarm public friend list rejected invalid response: {error}");
                    Vec::new()
                }
            }
        }
        Ok(response) => {
            log!(
                "ZombieFarm public friend list failed: server returned HTTP {}",
                response.status
            );
            Vec::new()
        }
        Err(error) => {
            log!("ZombieFarm public friend list failed: {error}");
            Vec::new()
        }
    };

    let neighbors: id = msg_class![env; NSMutableArray new];
    let game_state: id = msg_class![env; GameState gameState];
    let game_neighbors: id = if game_state == nil {
        nil
    } else {
        let existing: id = msg![env; game_state neighborsDictionary];
        if existing == nil {
            msg_class![env; NSMutableDictionary new]
        } else {
            msg![env; existing mutableCopy]
        }
    };
    let mut used = HashSet::new();
    let mut id_map = HashMap::new();
    for friend in friends {
        if friend.public_id.is_empty()
            || friend.public_id.len() > 80
            || friend.username.trim().is_empty()
        {
            continue;
        }
        let numeric_id = zombie_farm_public_friend_numeric_id(&friend.public_id, &used);
        let username_text = friend.username.trim().to_string();
        used.insert(numeric_id);
        id_map.insert(
            numeric_id,
            ZombieFarmPublicFriendIdentity {
                public_id: friend.public_id,
                username: username_text.clone(),
            },
        );

        let user: id = msg_class![env; UserData new];
        let username = ns_string::from_rust_string(env, username_text);
        let username = autorelease(env, username);
        let empty = ns_string::from_rust_string(env, String::new());
        let empty = autorelease(env, empty);
        let _: () = msg![env; user setUserIdentifier:numeric_id];
        let _: () = msg![env; user setUserName:username];
        let _: () = msg![env; user setFacebookID:empty];
        let _: () = msg![env; user setUserLevel:1i8];
        let _: () = msg![env; user setActivityLevel:0i8];
        let _: () = msg![env; user setHeadID:0i8];
        let _: () = msg![env; user setTimeTilGiftable:0i32];
        let _: () = msg![env; user setTimeTilTagable:0i32];
        let _: () = msg![env; neighbors addObject:user];
        release(env, user);

        // friendProfileUpdated: looks up the selected profile ID in
        // GameState.neighborsDictionary before it updates the visiting HUD.
        // The public list is otherwise only visible to SocialTableViewNeighbors,
        // leaving that lookup nil even though the remote GameData loaded and the
        // map was switched successfully.
        if game_neighbors != nil {
            let profile_id = ns_string::from_rust_string(env, format!("P{numeric_id}"));
            let profile_id = autorelease(env, profile_id);
            let neighbor: id = msg_class![env; ZFNeighbor new];
            let _: () = msg![env; neighbor setPlayforgeID:numeric_id];
            let _: () = msg![env; neighbor setAlias:username];
            let _: () = msg![env; neighbor setFacebookID:empty];
            let _: () = msg![env; neighbor setHeadID:0i32];
            let _: () = msg![env; neighbor setLevel:1i32];
            let _: () = msg![env; neighbor setInteractionLevel:0i32];
            let _: () = msg![env; neighbor setMinutesUntilGift:0i32];
            let _: () = msg![env; neighbor setMinutesUntilTag:0i32];
            let _: () = msg![env; game_neighbors setObject:neighbor forKey:profile_id];
            release(env, neighbor);
        }
    }
    *zombie_farm_public_friend_ids().lock().unwrap() = id_map;

    if game_neighbors != nil {
        let _: () = msg![env; game_state setNeighborsDictionary:game_neighbors];
        release(env, game_neighbors);
    }

    let count: NSUInteger = msg![env; neighbors count];
    let _: () = msg![env; friends_table setNeighborsData:neighbors];

    // The table view does not render directly from neighborsData. Its data source
    // reads the "neighbors" and "pending" arrays from neighborsTableData.
    let table_data: id = msg_class![env; NSMutableDictionary new];
    let neighbors_key = ns_string::from_rust_string(env, "neighbors".to_string());
    let neighbors_key = autorelease(env, neighbors_key);
    let pending_key = ns_string::from_rust_string(env, "pending".to_string());
    let pending_key = autorelease(env, pending_key);
    let pending: id = msg_class![env; NSMutableArray new];
    let _: () = msg![env; table_data setObject:neighbors forKey:neighbors_key];
    let _: () = msg![env; table_data setObject:pending forKey:pending_key];
    let _: () = msg![env; friends_table setNeighborsTableData:table_data];
    let _: () = msg![env; friends_table setPendingInvitesData:pending];
    let _: () = msg![env; friends_table setAwaitingApprovalData:pending];
    release(env, pending);
    release(env, table_data);

    let table_view: id = msg![env; friends_table tableView];
    let mut sections = 0i32;
    let mut rows = 0i32;
    let _: () = msg![env; friends_table setTutorialMode:false];
    if zombie_farm_complete_social_tutorial(env, "friend list refresh") {
        let social_menu: id = if from_social_menu {
            receiver
        } else {
            msg_class![env; SocialMenu socialMenu]
        };
        if social_menu != nil {
            let _: () = msg![env; social_menu tutorialNextStep];
        }
    }
    if table_view != nil {
        let _: () = msg![env; table_view reloadData];
        sections = msg![env; friends_table numberOfSectionsInTableView:table_view];
        for section in 0..sections {
            let section_rows: i32 =
                msg![env; friends_table tableView:table_view numberOfRowsInSection:section];
            rows += section_rows;
        }
    }
    release(env, neighbors);
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm public friend list loaded with {count} farm(s), table has {sections} section(s) and {rows} row(s)"
    );
    true
}

fn zombie_farm_load_public_friend_profile(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if selector_name != "updateProfile:forFriend:"
        || zombie_farm_object_class_name(env, receiver) != Some("PlayerProfileManager")
    {
        return false;
    }
    let Some(base_url) = ns_url_connection::zombie_farm_http_base_url(env) else {
        return false;
    };
    let profile_id_object = id::from_bits(env.cpu.regs()[2]);
    if profile_id_object == nil {
        return false;
    }
    let profile_id = ns_string::to_rust_string(env, profile_id_object).into_owned();
    let Some(numeric_id) = profile_id
        .strip_prefix('P')
        .and_then(|value| value.parse::<i32>().ok())
    else {
        return false;
    };
    let Some(public_friend) = zombie_farm_public_friend_ids()
        .lock()
        .unwrap()
        .get(&numeric_id)
        .cloned()
    else {
        return false;
    };
    let public_id = public_friend.public_id;

    let url = format!(
        "{}/v1/farms/{}/save",
        base_url,
        zombie_farm_percent_encode(&public_id)
    );
    let save = match ns_url_connection::zombie_farm_http_request("GET", &url, &[], Vec::new()) {
        Ok(response) if response.status == 200 && !response.body.is_empty() => response.body,
        Ok(response) => {
            log!(
                "ZombieFarm public friend farm fetch failed for {}: HTTP {}",
                public_id,
                response.status
            );
            return false;
        }
        Err(error) => {
            log!(
                "ZombieFarm public friend farm fetch failed for {}: {}",
                public_id,
                error
            );
            return false;
        }
    };
    if save.len() > 4 << 20 {
        log!(
            "ZombieFarm public friend farm fetch rejected oversized save for {}",
            public_id
        );
        return false;
    }

    let neighbor_directory = env.fs.home_directory().join("Documents/neighborData");
    if env.fs.create_dir_all(neighbor_directory.clone()).is_err() {
        log!("ZombieFarm public friend farm could not create neighborData directory");
        return false;
    }
    let save_file_name = format!("saveGame_{profile_id}.friend");
    let save_path = neighbor_directory.join(&save_file_name);
    if env.fs.write(&save_path, &save).is_err() {
        log!("ZombieFarm public friend farm could not write {profile_id}");
        return false;
    }

    let save_file_name = ns_string::from_rust_string(env, save_file_name);
    let exception_ptr: MutPtr<id> = env.mem.alloc(guest_size_of::<id>()).cast();
    env.mem.write(exception_ptr, nil);
    let game_data: id = msg_class![env; GameData
        gameDataFromBinayFile:save_file_name
        asFriend:true
        exception_p:exception_ptr];
    let exception: id = env.mem.read(exception_ptr);
    env.mem.free(exception_ptr.cast());
    release(env, save_file_name);
    if game_data == nil {
        if exception == nil {
            log!("ZombieFarm public friend binary decoder returned no GameData for {profile_id}");
        } else {
            let description: id = msg![env; exception description];
            let description = if description == nil {
                "(unknown exception)".to_string()
            } else {
                ns_string::to_rust_string(env, description).into_owned()
            };
            log!("ZombieFarm public friend binary decoder failed for {profile_id}: {description}");
        }
        return false;
    }

    let profile: id = msg_class![env; PlayerProfile alloc];
    let profile: id = msg![env; profile initWithGameData:game_data];
    if profile == nil {
        log!("ZombieFarm public friend farm could not load {profile_id}");
        return false;
    }
    let profile_alias = ns_string::from_rust_string(env, public_friend.username.clone());
    let profile_alias = autorelease(env, profile_alias);
    let _: () = msg![env; profile setPlayerProfileID:profile_id_object];
    let _: () = msg![env; profile setPlayerProfileType:2i32];
    let _: () = msg![env; profile setPlayforgeID:numeric_id];
    let _: () = msg![env; profile setPlayforgeAlias:profile_alias];
    let _: () = msg![env; profile setDisplayName:profile_alias];
    let _: () = msg![env; game_data setPlayerProfileID:profile_id_object];
    let _: () = msg![env; game_data setPlayforgeID:numeric_id];
    let _: () = msg![env; game_data setPlayforgeAlias:profile_alias];

    // SocialMenu can rebuild GameState.neighborsDictionary after the public
    // table was populated. Reinstall the selected identity immediately before
    // friendProfileUpdated: consumes it for changeHudToVisiting:.
    let game_state: id = msg_class![env; GameState gameState];
    if game_state != nil {
        let existing: id = msg![env; game_state neighborsDictionary];
        let game_neighbors: id = if existing == nil {
            msg_class![env; NSMutableDictionary new]
        } else {
            msg![env; existing mutableCopy]
        };
        let username = ns_string::from_rust_string(env, public_friend.username);
        let username = autorelease(env, username);
        let empty = ns_string::from_rust_string(env, String::new());
        let empty = autorelease(env, empty);
        let neighbor: id = msg_class![env; ZFNeighbor new];
        let _: () = msg![env; neighbor setPlayforgeID:numeric_id];
        let _: () = msg![env; neighbor setAlias:username];
        let _: () = msg![env; neighbor setFacebookID:empty];
        let _: () = msg![env; neighbor setHeadID:0i32];
        let _: () = msg![env; neighbor setLevel:1i32];
        let _: () = msg![env; neighbor setInteractionLevel:0i32];
        let _: () = msg![env; neighbor setMinutesUntilGift:0i32];
        let _: () = msg![env; neighbor setMinutesUntilTag:0i32];
        let _: () = msg![env; game_neighbors setObject:neighbor forKey:profile_id_object];
        let _: () = msg![env; game_state setNeighborsDictionary:game_neighbors];
        release(env, neighbor);
        release(env, game_neighbors);
    }

    let result: id = msg_class![env; NSMutableDictionary new];
    let profile_key = ns_string::from_rust_string(env, "playerProfile".to_string());
    let profile_key = autorelease(env, profile_key);
    let _: () = msg![env; result setObject:profile forKey:profile_key];
    let game_data: id = msg![env; profile playerGameData];
    let dictionary_class = env.objc.get_known_class("NSDictionary", &mut env.mem);
    let null_class = env.objc.get_known_class("NSNull", &mut env.mem);
    let result_is_dictionary: bool = msg![env; result isKindOfClass:dictionary_class];
    let profile_is_null: bool = msg![env; profile isKindOfClass:null_class];
    let game_data_is_null: bool = if game_data == nil {
        false
    } else {
        msg![env; game_data isKindOfClass:null_class]
    };
    log!(
        "ZombieFarm public friend profile validation: resultDictionary={}, profileNull={}, gameData={:?} (class {:?}, null={})",
        result_is_dictionary,
        profile_is_null,
        game_data,
        zombie_farm_object_class_name(env, game_data),
        game_data_is_null
    );
    zombie_farm_post_notification_name_object(env, "kProfileUpdatedNotification", result);
    release(env, result);
    release(env, profile);
    env.cpu.regs_mut()[0] = 0;
    log!(
        "ZombieFarm public friend farm loaded {} as {}",
        public_id,
        profile_id
    );
    true
}

fn zombie_farm_load_public_giftable_friends(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) -> bool {
    if !matches!(
        selector_name,
        "getGiftableNeighbors" | "showNeighborsForGifting"
    ) || zombie_farm_object_class_name(env, receiver) != Some("SocialTableViewGifts")
    {
        return false;
    }
    if ns_url_connection::zombie_farm_http_base_url(env).is_none() {
        return false;
    }

    let social_menu: id = msg_class![env; SocialMenu socialMenu];
    if social_menu == nil {
        return false;
    }
    let friends_table: id = msg![env; social_menu friendsTable];
    if friends_table == nil
        || !zombie_farm_load_public_friend_list(env, friends_table, "getFriendsList")
    {
        return false;
    }

    let public_friends: id = msg![env; friends_table neighborsData];
    if public_friends == nil {
        return false;
    }
    let giftable: id = msg_class![env; NSMutableArray new];
    let count: NSUInteger = msg![env; public_friends count];
    for index in 0..count {
        let user: id = msg![env; public_friends objectAtIndex:index];
        if user == nil {
            continue;
        }
        let playforge_id: i32 = msg![env; user userIdentifier];
        let alias: id = msg![env; user userName];
        let facebook_id: id = msg![env; user facebookID];
        let head_id: i8 = msg![env; user headID];
        let head_id = i32::from(head_id);

        let neighbor: id = msg_class![env; ZFNeighbor new];
        let _: () = msg![env; neighbor setPlayforgeID:playforge_id];
        let _: () = msg![env; neighbor setAlias:alias];
        let _: () = msg![env; neighbor setFacebookID:facebook_id];
        let _: () = msg![env; neighbor setHeadID:head_id];
        let _: () = msg![env; neighbor setLevel:1i32];
        let _: () = msg![env; neighbor setInteractionLevel:0i32];
        let _: () = msg![env; neighbor setMinutesUntilGift:0i32];
        let _: () = msg![env; neighbor setMinutesUntilTag:0i32];
        let _: () = msg![env; giftable addObject:neighbor];
        release(env, neighbor);
    }

    let giftable_count: NSUInteger = msg![env; giftable count];
    let _: () = msg![env; receiver setGiftableFriendsData:giftable];
    release(env, giftable);
    let table_view: id = msg![env; receiver tableView];
    if table_view != nil {
        let _: () = msg![env; table_view reloadData];
    }
    zombie_farm_post_notification_name_object(env, "kGiftingNeighborsRetrieved", nil);
    env.cpu.regs_mut()[0] = 0;
    log!("ZombieFarm public gift list loaded with {giftable_count} neighbor(s)");
    true
}

fn zombie_farm_publish_public_farm(env: &mut Environment, context: &str) {
    let Some(base_url) = ns_url_connection::zombie_farm_http_base_url(env) else {
        return;
    };
    let player_name = std::env::var("TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME")
        .ok()
        .filter(|name| !name.trim().is_empty())
        .unwrap_or_else(|| "Zombie Farmer".to_string());
    let local_player: id = msg_class![env; GKLocalPlayer localPlayer];
    if local_player == nil {
        log!("ZombieFarm public farm publish skipped: local player is unavailable");
        return;
    }
    let player_id: id = msg![env; local_player playerID];
    if player_id == nil {
        log!("ZombieFarm public farm publish skipped: public ID is unavailable");
        return;
    }
    let player_id = ns_string::to_rust_string(env, player_id).into_owned();
    let save_path = env.fs.home_directory().join("Documents/saveGame.bin2");
    let Ok(save) = env.fs.read(&save_path) else {
        log!("ZombieFarm public farm publish skipped: saveGame.bin2 is unavailable");
        return;
    };
    if save.is_empty() || save.len() > 4 << 20 {
        log!(
            "ZombieFarm public farm publish skipped: save size {} is invalid",
            save.len()
        );
        return;
    }

    let digest: [u8; 32] = Sha256::digest(&save).into();
    static LAST_PUBLISHED_DIGEST: OnceLock<Mutex<Option<[u8; 32]>>> = OnceLock::new();
    let last_digest = LAST_PUBLISHED_DIGEST.get_or_init(|| Mutex::new(None));
    if *last_digest.lock().unwrap() == Some(digest) {
        return;
    }

    let url = format!(
        "{}/v1/farms/{}?username={}",
        base_url,
        player_id,
        zombie_farm_percent_encode(&player_name)
    );
    let headers = vec![(
        "Content-Type".to_string(),
        "application/octet-stream".to_string(),
    )];
    match ns_url_connection::zombie_farm_http_request("PUT", &url, &headers, save) {
        Ok(response) if response.status == 200 => {
            *last_digest.lock().unwrap() = Some(digest);
            log!(
                "ZombieFarm public farm published after {} as {}",
                context,
                player_id
            );
        }
        Ok(response) => {
            log!(
                "ZombieFarm public farm publish failed after {}: HTTP {}",
                context,
                response.status
            );
        }
        Err(error) => {
            log!(
                "ZombieFarm public farm publish failed after {}: {}",
                context,
                error
            );
        }
    }
}

fn zombie_farm_percent_encode(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            encoded.push(byte as char);
        } else {
            use std::fmt::Write;
            write!(&mut encoded, "%{:02X}", byte).unwrap();
        }
    }
    encoded
}

pub(super) fn zombie_farm_pre_dispatch_workarounds(
    env: &mut Environment,
    receiver: id,
    selector: SEL,
    selector_name: &str,
) -> bool {
    let _profile = crate::zfr_profile::scope(crate::zfr_profile::Category::ZombiePreDispatch);
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }

    if zombie_farm_sprite_trace_enabled() {
        trace_zombie_farm_sprite_message(env, receiver, selector_name);
    }

    if zombie_farm_override_active_player_display_name(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_override_public_game_center_profile(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_load_public_friend_list(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_load_public_friend_profile(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_load_public_giftable_friends(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_override_invasion_cooldown_interval(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_sanitize_ccarray_before_cleanup(env, receiver, selector_name) {
        return true;
    }

    if zombie_farm_repair_ccaction_manager_targets(env, receiver, selector_name) {
        return true;
    }

    zombie_farm_repair_ccnode_children_before_visit(env, receiver, selector_name);

    if env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2" {
        zombie_farm_trace_game_interaction_message(env, receiver, selector_name);
        zombie_farm_force_status_bar_timeout(env, receiver, selector_name);
        if zombie_farm_ignore_spurious_operation_done(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_forward_backing_array_fast_enumeration(
            env,
            receiver,
            selector,
            selector_name,
        ) {
            return true;
        }
        if zombie_farm_ignore_null_attachment_placeholder(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_force_zombie_hunger_message(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_object_class_name(env, receiver) == Some("MainMenu")
            || selector_name == "playTapped"
        {
            ZOMBIE_FARM_LAST_MAIN_MENU.store(receiver.to_bits() as usize, Ordering::Relaxed);
            if selector_name == "playTapped" {
                log!(
                    "ZombieFarm2 workaround: remembered {:?} ({}) as MainMenu candidate",
                    receiver,
                    zombie_farm_object_class_name(env, receiver).unwrap_or("unknown")
                );
            }
        }
        if let Some(result) = zombie_farm_md5sum_override(env, selector_name) {
            env.cpu.regs_mut()[0] = result.to_bits();
            return true;
        }
        if zombie_farm_skip_redundant_zombie_cell_rebuild(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_disable_cctable_cell_reuse(env, receiver, selector_name) {
            return true;
        }
        zombie_farm_prepare_game_state_save_date(env, receiver, selector_name);
        if zombie_farm_skip_epic_event_with_missing_remote_data(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_override_cocos2d_get_zeye(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_cocos2d_projection_setup(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_remote_asset_requests(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_event_tracker_nil_last_event(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_event_tracker_init(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_return_open_udid(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_vungle_ad_sdk(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_broken_font_preload(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_brain_client_network(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_sync_queue_network(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_return_safe_game_state_count(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_remote_dependent_game_state_update(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_return_self_for_game_data_copy(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_host_actor_manager_init(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_tool_manager_transient_actions(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_quest_manager_reset(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_unsafe_toolbar_build(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_market_offers(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_event_ad_networks(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_farmer_head_modal(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_host_load_farm_scene(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_startup_profile_detection(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_startup_internet_loading(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_cocos_denshion_effects(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_route_eagl_view_touches(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_host_cocos_touch_dispatcher(env, receiver, selector_name) {
            return true;
        }
        if zombie_farm_skip_unsafe_cocos_touch_dispatch(env, receiver, selector_name) {
            return true;
        }
        zombie_farm_prepare_local_server_date(env, receiver, selector_name);
        zombie_farm_prepare_local_hunger_update(env, selector_name);
        return false;
    }

    match selector_name {
        "operationDone" => {
            if zombie_farm_ignore_spurious_operation_done(env, receiver, selector_name) {
                return true;
            }
        }
        "objectForKey:" => {
            if zombie_farm_disable_legacy_status_check_for_public_online(
                env,
                receiver,
                selector_name,
            ) {
                return true;
            }
        }
        "showUnableToVisitError:" => {
            log!(
                "ZombieFarm public friend visit failure: [{} showUnableToVisitError:{}], guest LR=0x{:08x}",
                zombie_farm_object_class_name(env, receiver).unwrap_or("unknown"),
                env.cpu.regs()[2] != 0,
                env.cpu.regs()[14]
            );
        }
        "statusMessage:cancelAfter:"
        | "showMessage:withCancelTimeout:andCancelNotification:"
        | "updateMessage:andCancelTimeout:andCancelNotification:" => {
            zombie_farm_force_status_bar_timeout(env, receiver, selector_name);
        }
        "getAverageHunger" | "hunger" | "setHunger:" => {
            if zombie_farm_force_zombie_hunger_message(env, receiver, selector_name) {
                return true;
            }
        }
        "md5sum:" => {
            if let Some(result) = zombie_farm_md5sum_override(env, selector_name) {
                env.cpu.regs_mut()[0] = result.to_bits();
                return true;
            }
        }
        "setZombie:" | "dealloc" => {
            if zombie_farm_skip_redundant_zombie_cell_rebuild(env, receiver, selector_name) {
                return true;
            }
        }
        "dequeueCell" => {
            if zombie_farm_disable_cctable_cell_reuse(env, receiver, selector_name) {
                return true;
            }
        }
        "setSaveDate:" => {
            zombie_farm_prepare_game_state_save_date(env, receiver, selector_name);
        }
        "getBeginningOfTheDayFromDate:" => {
            if zombie_farm_return_local_beginning_of_day(env, receiver, selector_name) {
                return true;
            }
        }
        "getServerTime" => {
            if zombie_farm_complete_server_time_locally(env, receiver, selector_name) {
                return true;
            }
            zombie_farm_prepare_local_server_date(env, receiver, selector_name);
        }
        "handleResponse:forAction:" => {
            if zombie_farm_complete_legacy_social_response(env, receiver, selector_name) {
                return true;
            }
            zombie_farm_prepare_local_server_date(env, receiver, selector_name);
        }
        "handlePotentialFriendsResponse:" => {
            if zombie_farm_skip_obsolete_potential_friends_response(env, receiver, selector_name) {
                return true;
            }
        }
        "acceptGift" => {
            if zombie_farm_skip_unsafe_gift_action(env, receiver, selector_name) {
                return true;
            }
        }
        "dismissMenu:" => {
            if zombie_farm_complete_stale_tag_summary_dismiss(env, receiver, selector_name) {
                return true;
            }
        }
        "inputDailyBonusReward:alert:" => {
            zombie_farm_acknowledge_daily_reward_confirmation(env, receiver);
        }
        "openMenu"
        | "openMenuThroughMausoleum"
        | "displayCurrentZombie"
        | "updateSelectedZombieInfo"
        | "displayHunger"
        | "table:cellTouched:"
        | "saveGame"
        | "startInvasion:"
        | "startInvasion:checkHunger:"
        | "startInvasionWithDictionary:checkHunger:"
        | "invadeButtonTapped:"
        | "switchToFightScene" => {
            if selector_name == "saveGame" {
                zombie_farm_complete_social_tutorial(env, "saveGame");
            }
            zombie_farm_prepare_local_hunger_update(env, selector_name);
        }
        _ => {}
    }

    false
}

pub(super) fn zombie_farm_needs_pre_dispatch_workarounds(
    env: &Environment,
    selector_name: &str,
) -> bool {
    if !zombie_farm_uses_playforge_bundle(env) {
        return false;
    }

    if zombie_farm_sprite_trace_enabled()
        || env.bundle.bundle_identifier() == "com.playforge.ZombieFarm2"
    {
        return true;
    }

    if zombie_farm_is_exact_legacy_app(env)
        && zombie_farm_no_invasion_cooldown_enabled()
        && matches!(
            selector_name,
            "timeIntervalSinceNow" | "timeIntervalSinceDate:"
        )
    {
        return true;
    }

    matches!(
        selector_name,
        "operationDone"
            | "objectForKey:"
            | "showUnableToVisitError:"
            | "statusMessage:cancelAfter:"
            | "showMessage:withCancelTimeout:andCancelNotification:"
            | "updateMessage:andCancelTimeout:andCancelNotification:"
            | "getAverageHunger"
            | "hunger"
            | "setHunger:"
            | "md5sum:"
            | "setZombie:"
            | "visit"
            | "dealloc"
            | "removeAllObjects"
            | "update:"
            | "resumeTarget:"
            | "_moveCellOutOfSight:"
            | "dequeueCell"
            | "setSaveDate:"
            | "getBeginningOfTheDayFromDate:"
            | "getServerTime"
            | "handleResponse:forAction:"
            | "handlePotentialFriendsResponse:"
            | "acceptGift"
            | "dismissMenu:"
            | "inputDailyBonusReward:alert:"
            | "openMenu"
            | "openMenuThroughMausoleum"
            | "displayCurrentZombie"
            | "updateSelectedZombieInfo"
            | "displayHunger"
            | "table:cellTouched:"
            | "saveGame"
            | "startInvasion:"
            | "startInvasion:checkHunger:"
            | "startInvasionWithDictionary:checkHunger:"
            | "invadeButtonTapped:"
            | "switchToFightScene"
            | "displayName"
            | "playerProfileType"
            | "playerGameCenterID"
            | "gameCenterAlias"
            | "playforgeAlias"
            | "getFriendsList"
            | "findFriends"
            | "findFriends:"
            | "updateProfile:forFriend:"
            | "getGiftableNeighbors"
            | "showNeighborsForGifting"
    )
}

#[cfg(test)]
mod tests {
    use super::{
        zombie_farm_calendar_day_in_timezone, zombie_farm_cocos_win_size,
        zombie_farm_env_flag_enabled, zombie_farm_invasion_interval_override,
        zombie_farm_is_ccaction_manager_workaround_call, zombie_farm_is_legacy_social_response,
        zombie_farm_is_obsolete_potential_friends_response,
        zombie_farm_is_tag_summary_win_size_call, zombie_farm_is_unsafe_legacy_gift_action,
        zombie_farm_legacy_compatible_day_in_timezone, zombie_farm_start_of_local_day_in_timezone,
        ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS, ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN,
    };
    use crate::frameworks::core_graphics::CGSize;
    use chrono::{FixedOffset, NaiveDate, TimeZone, Utc};

    fn unix_seconds(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32) -> f64 {
        Utc.with_ymd_and_hms(year, month, day, hour, minute, second)
            .single()
            .unwrap()
            .timestamp() as f64
    }

    #[test]
    fn zombie_farm_migrates_legacy_utc_midnight_to_utc_plus_eight() {
        let time_zone = FixedOffset::east_opt(8 * 60 * 60).unwrap();
        let legacy_midnight = unix_seconds(2026, 7, 30, 0, 0, 0);
        let (day, start, migrated) =
            zombie_farm_start_of_local_day_in_timezone(legacy_midnight, &time_zone).unwrap();

        assert_eq!(day, NaiveDate::from_ymd_opt(2026, 7, 30).unwrap());
        assert_eq!(start, unix_seconds(2026, 7, 29, 16, 0, 0));
        assert!(migrated);
    }

    #[test]
    fn zombie_farm_migrates_legacy_utc_midnight_to_utc_minus_eight() {
        let time_zone = FixedOffset::west_opt(8 * 60 * 60).unwrap();
        let legacy_midnight = unix_seconds(2026, 7, 30, 0, 0, 0);
        let (day, start, migrated) =
            zombie_farm_start_of_local_day_in_timezone(legacy_midnight, &time_zone).unwrap();

        assert_eq!(day, NaiveDate::from_ymd_opt(2026, 7, 30).unwrap());
        assert_eq!(start, unix_seconds(2026, 7, 30, 8, 0, 0));
        assert!(migrated);
    }

    #[test]
    fn zombie_farm_uses_local_calendar_day_for_ordinary_instants() {
        let time_zone = FixedOffset::west_opt(8 * 60 * 60).unwrap();
        let instant = unix_seconds(2026, 7, 30, 1, 0, 0);
        let (day, start, migrated) =
            zombie_farm_start_of_local_day_in_timezone(instant, &time_zone).unwrap();

        assert_eq!(day, NaiveDate::from_ymd_opt(2026, 7, 29).unwrap());
        assert_eq!(start, unix_seconds(2026, 7, 29, 8, 0, 0));
        assert!(!migrated);
    }

    #[test]
    fn zombie_farm_daily_reward_changes_at_utc_plus_eight_midnight() {
        let time_zone = FixedOffset::east_opt(8 * 60 * 60).unwrap();
        let display = unix_seconds(2026, 7, 30, 0, 0, 0);
        let previous_day =
            zombie_farm_legacy_compatible_day_in_timezone(display, &time_zone).unwrap();
        let before_midnight =
            zombie_farm_calendar_day_in_timezone(unix_seconds(2026, 7, 30, 15, 59, 59), &time_zone)
                .unwrap();
        let at_midnight =
            zombie_farm_calendar_day_in_timezone(unix_seconds(2026, 7, 30, 16, 0, 0), &time_zone)
                .unwrap();

        assert_eq!(before_midnight, previous_day);
        assert!(at_midnight > previous_day);
    }

    #[test]
    fn zombie_farm_daily_reward_changes_at_utc_minus_eight_midnight() {
        let time_zone = FixedOffset::west_opt(8 * 60 * 60).unwrap();
        let display = unix_seconds(2026, 7, 30, 0, 0, 0);
        let previous_day =
            zombie_farm_legacy_compatible_day_in_timezone(display, &time_zone).unwrap();
        let before_midnight =
            zombie_farm_calendar_day_in_timezone(unix_seconds(2026, 7, 31, 7, 59, 59), &time_zone)
                .unwrap();
        let at_midnight =
            zombie_farm_calendar_day_in_timezone(unix_seconds(2026, 7, 31, 8, 0, 0), &time_zone)
                .unwrap();

        assert_eq!(before_midnight, previous_day);
        assert!(at_midnight > previous_day);
    }

    #[test]
    fn zombie_farm_only_skips_the_exact_legacy_social_response_method() {
        assert!(zombie_farm_is_legacy_social_response(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialMenu"),
            "handleResponse:forAction:",
        ));
        assert!(!zombie_farm_is_legacy_social_response(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("ZFGuiLayer"),
            "handleResponse:forAction:",
        ));
        assert!(!zombie_farm_is_legacy_social_response(
            "com.playforge.ZombieFarm2",
            "1.0",
            Some("SocialMenu"),
            "handleResponse:forAction:",
        ));
    }

    #[test]
    fn zombie_farm_skips_accept_gift_for_detached_or_public_legacy_gifts_table() {
        assert!(zombie_farm_is_unsafe_legacy_gift_action(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewGifts"),
            "acceptGift",
            true,
            false,
            false,
        ));
        assert!(zombie_farm_is_unsafe_legacy_gift_action(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewGifts"),
            "acceptGift",
            false,
            false,
            false,
        ));
        assert!(zombie_farm_is_unsafe_legacy_gift_action(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewGifts"),
            "acceptGift",
            true,
            true,
            true,
        ));
        assert!(!zombie_farm_is_unsafe_legacy_gift_action(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewGifts"),
            "acceptGift",
            true,
            true,
            false,
        ));
        assert!(!zombie_farm_is_unsafe_legacy_gift_action(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialMenu"),
            "acceptGift",
            true,
            false,
            true,
        ));
    }

    #[test]
    fn zombie_farm_skips_obsolete_potential_friends_response_in_both_network_modes() {
        assert!(zombie_farm_is_obsolete_potential_friends_response(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewFacebook"),
            "handlePotentialFriendsResponse:",
        ));
        assert!(!zombie_farm_is_obsolete_potential_friends_response(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("SocialTableViewNeighbors"),
            "handlePotentialFriendsResponse:",
        ));
        assert!(!zombie_farm_is_obsolete_potential_friends_response(
            "com.playforge.ZombieFarm2",
            "1.0",
            Some("SocialTableViewFacebook"),
            "handlePotentialFriendsResponse:",
        ));
    }

    #[test]
    fn zombie_farm_only_overrides_tag_summary_win_size_at_the_exact_return_site() {
        assert!(zombie_farm_is_tag_summary_win_size_call(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("CCFastDirector"),
            "winSize",
            ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN,
        ));
        assert!(!zombie_farm_is_tag_summary_win_size_call(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("CCFastDirector"),
            "winSize",
            ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN + 4,
        ));
        assert!(!zombie_farm_is_tag_summary_win_size_call(
            "com.playforge.ZFR.LZ54D2GT3D",
            "1.0",
            Some("ZFTagSummary"),
            "winSize",
            ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN,
        ));
        assert!(!zombie_farm_is_tag_summary_win_size_call(
            "com.playforge.ZombieFarm2",
            "1.0",
            Some("CCFastDirector"),
            "winSize",
            ZOMBIE_FARM_TAG_SUMMARY_WIN_SIZE_RETURN,
        ));
    }

    #[test]
    fn zombie_farm_win_size_matches_cocos_landscape_orientation_rules() {
        let surface_size = CGSize {
            width: 768.0,
            height: 1024.0,
        };

        assert_eq!(zombie_farm_cocos_win_size(1, surface_size), surface_size);
        assert_eq!(
            zombie_farm_cocos_win_size(3, surface_size),
            CGSize {
                width: 1024.0,
                height: 768.0,
            }
        );
        assert_eq!(
            zombie_farm_cocos_win_size(4, surface_size),
            CGSize {
                width: 1024.0,
                height: 768.0,
            }
        );
    }

    #[test]
    fn zombie_farm_parses_no_invasion_cooldown_environment_flag() {
        for enabled in ["1", "true", "TRUE", " yes ", "On"] {
            assert!(zombie_farm_env_flag_enabled(Some(enabled)));
        }
        for disabled in ["", "0", "false", "no", "off", "2"] {
            assert!(!zombie_farm_env_flag_enabled(Some(disabled)));
        }
        assert!(!zombie_farm_env_flag_enabled(None));
    }

    #[test]
    fn zombie_farm_only_overrides_intervals_for_last_invasion_date() {
        assert_eq!(
            zombie_farm_invasion_interval_override(true, "timeIntervalSinceNow", true, false,),
            Some(-ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS)
        );
        assert_eq!(
            zombie_farm_invasion_interval_override(true, "timeIntervalSinceDate:", false, true,),
            Some(ZOMBIE_FARM_INVASION_READY_INTERVAL_SECONDS)
        );
        assert_eq!(
            zombie_farm_invasion_interval_override(true, "timeIntervalSinceNow", false, false,),
            None
        );
        assert_eq!(
            zombie_farm_invasion_interval_override(true, "timeIntervalSinceDate:", true, false,),
            None
        );
        assert_eq!(
            zombie_farm_invasion_interval_override(false, "timeIntervalSinceNow", true, false,),
            None
        );
    }

    #[test]
    fn zombie_farm_only_repairs_legacy_ccaction_manager_update_and_resume() {
        assert!(zombie_farm_is_ccaction_manager_workaround_call(
            true,
            Some("CCActionManager"),
            "update:",
        ));
        assert!(zombie_farm_is_ccaction_manager_workaround_call(
            true,
            Some("CCActionManager"),
            "resumeTarget:",
        ));
        assert!(!zombie_farm_is_ccaction_manager_workaround_call(
            true,
            Some("CCRepeatForever"),
            "update:",
        ));
        assert!(!zombie_farm_is_ccaction_manager_workaround_call(
            false,
            Some("CCActionManager"),
            "update:",
        ));
    }
}

pub(super) fn zombie_farm_post_dispatch_workarounds(
    env: &mut Environment,
    receiver: id,
    selector_name: &str,
) {
    let _profile = crate::zfr_profile::scope(crate::zfr_profile::Category::ZombiePostDispatch);
    if !zombie_farm_uses_playforge_bundle(env) {
        return;
    }

    if zombie_farm_touch_trace_enabled() {
        zombie_farm_trace_game_interaction_return(env, receiver, selector_name);
    }

    zombie_farm_record_last_invasion_date(env, receiver, selector_name);

    match selector_name {
        "handleTimeResponse:" => {
            zombie_farm_apply_local_hunger_update(env, receiver, selector_name);
            zombie_farm_trace_daily_reward_gate(env, receiver);
        }
        "statusCheckDone" | "startUpChecksComplete" => {
            zombie_farm_complete_social_tutorial(env, selector_name);
            zombie_farm_apply_local_hunger_update(env, receiver, selector_name);
            zombie_farm_check_local_daily_event(env, receiver, selector_name);
            zombie_farm_restore_local_quest_progress(env, receiver, selector_name);
            zombie_farm_publish_public_farm(env, selector_name);
        }
        "saveGame" => zombie_farm_publish_public_farm(env, selector_name),
        _ => {}
    }
}

pub(super) fn zombie_farm_needs_post_dispatch_workarounds(
    env: &Environment,
    selector_name: &str,
) -> bool {
    zombie_farm_uses_playforge_bundle(env)
        && (zombie_farm_touch_trace_enabled()
            || (zombie_farm_is_exact_legacy_app(env)
                && zombie_farm_no_invasion_cooldown_enabled()
                && selector_name == "lastInvasionDate")
            || matches!(
                selector_name,
                "handleTimeResponse:" | "statusCheckDone" | "startUpChecksComplete" | "saveGame"
            ))
}
