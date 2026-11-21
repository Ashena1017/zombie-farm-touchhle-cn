/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Offline completion of the original Zombie Camera's screenshot flow.

use super::{zombie_farm_get_gui_layer, zombie_farm_object_class_name};
use crate::cpu::Cpu;
use crate::frameworks::foundation::ns_string;
use crate::objc::{id, nil, release, IMP};
use crate::{msg, Environment};

const FINISH_CAPTURE: &str = "_touchHLE_finishZombieCameraCapture";
const NOTICE: &str = "本项目免费开源，请勿购买。\n\n项目地址\nhttps://github.com/Ashena1017/\nzombie-farm-touchhle-cn\n\nQQ 交流群 1185712984";

fn supported(env: &Environment) -> bool {
    env.bundle.bundle_identifier() == "com.playforge.ZombieFarm.ZFR"
        && env.bundle.bundle_version() == "1.0"
}

pub(super) fn needs_pre_dispatch(selector: &str) -> bool {
    matches!(
        selector,
        "connectedToInternet" | "chooseScreenCapUploadMethod" | FINISH_CAPTURE
    )
}

fn camera_reachability_check(env: &mut Environment, receiver: id) -> bool {
    if env.objc.try_get_class_name(receiver) != Some("Reachability") {
        return false;
    }
    let Some(take_photo) = env.objc.lookup_selector("takeScreenCap:") else {
        return false;
    };
    let manager = env.objc.get_known_class("ZFScreenshotManager", &mut env.mem);
    let Some(IMP::Guest(imp)) = env.objc.class_get_method_imp(manager, take_photo) else {
        return false;
    };
    // Match just the call inside -takeScreenCap:, in either original ARM
    // slice. Other game features continue to see the normal network status.
    let return_offset = if imp.is_thumb() { 0x88 } else { 0x78 };
    env.cpu.regs()[Cpu::LR] == imp.addr_with_thumb_bit() + return_offset
}

pub(super) fn pre_dispatch(env: &mut Environment, receiver: id, selector: &str) -> bool {
    if !needs_pre_dispatch(selector) || !supported(env) {
        return false;
    }
    if selector == "connectedToInternet" {
        if !camera_reachability_check(env, receiver) {
            return false;
        }
        env.cpu.regs_mut()[0] = 1;
        return true;
    }
    if zombie_farm_object_class_name(env, receiver) != Some("ZFScreenshotManager") {
        return false;
    }
    if selector == FINISH_CAPTURE {
        // The guest has finished its shutter fade. Use its own cleanup to
        // remove the touch blocker before putting the notice in the alert queue.
        let in_progress: bool = msg![env; receiver screenCapInProgress];
        let pending: bool = msg![env; receiver shotPending];
        if pending && !in_progress {
            let _: () = msg![env; receiver cleanupScreenCapData];
        }
        if let Some(gui) = zombie_farm_get_gui_layer(env) {
            let title = ns_string::from_rust_string(env, "免费开源声明".to_string());
            let message = ns_string::from_rust_string(env, NOTICE.to_string());
            let alert: id = msg![env; gui displayAlertSimple:title withMessage:message withSprite:nil];
            release(env, message);
            release(env, title);
            if alert != nil {
                log!("ZombieFarm: queued the free and open-source notice after taking a photo");
            }
        }
    } else {
        // Only a successful capture reaches the old share sheet. The
        // original callback can still play the sound and post its reward.
        let finish = env
            .objc
            .register_host_selector(FINISH_CAPTURE.to_string(), &mut env.mem);
        let _: () = msg![env; receiver performSelector:finish withObject:nil afterDelay:1.0_f64];
    }
    env.cpu.regs_mut()[0] = 0;
    true
}

pub(super) fn after_capture(env: &mut Environment, receiver: id) {
    if !supported(env)
        || zombie_farm_object_class_name(env, receiver) != Some("ZFScreenshotManager")
    {
        return;
    }
    let regs = *env.cpu.regs();
    // A failed image leaves the pending flag set in the original handler.
    let pending: bool = msg![env; receiver shotPending];
    let image: id = msg![env; receiver screenshot];
    if pending && image == nil {
        let _: () = msg![env; receiver setShotPending:false];
        let _: () = msg![env; receiver cleanupScreenCapData];
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}
