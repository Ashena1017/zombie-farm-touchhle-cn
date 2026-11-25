/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Help and the offline farm picker in Zombie Farm 1.0.

use super::{zombie_farm_object_class_name, zombie_farm_read_object_ivar};
use crate::frameworks::core_graphics::{CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::{ns_string, ns_url_connection};
use crate::frameworks::uikit::ui_font::UITextAlignmentCenter;
use crate::frameworks::uikit::ui_view::ui_control::UIControlStateNormal;
use crate::objc::{id, nil, release};
use crate::zfr_integrity::PROJECT_URL;
use crate::{msg, msg_class, Environment};

const NOTICE_TITLE: &str = "免费开源声明";

pub(super) fn post_dispatch(env: &mut Environment, receiver: id, selector: &str) {
    if !matches!(selector, "viewDidLoad" | "setProfilesData:")
        || env.bundle.bundle_identifier() != "com.playforge.ZombieFarm.ZFR"
        || env.bundle.bundle_version() != "1.0"
    {
        return;
    }
    let regs = *env.cpu.regs();
    match (selector, zombie_farm_object_class_name(env, receiver)) {
        ("viewDidLoad", Some("ZFHelpMenu")) => prepend_help_notice(env, receiver),
        ("setProfilesData:", Some("AccountsMenu"))
            if ns_url_connection::zombie_farm_http_base_url(env).is_none() =>
        {
            finish_offline_farm_picker(env, receiver);
        }
        _ => return,
    }
    env.cpu.regs_mut().copy_from_slice(&regs);
}

fn prepend_help_notice(env: &mut Environment, controller: id) {
    let text_view: id = msg![env; controller scrollTextView];
    let body: id = msg![env; text_view text];
    if body == nil {
        return;
    }
    let body = ns_string::to_rust_string(env, body);
    if body.starts_with(NOTICE_TITLE) {
        return;
    }
    let text = ns_string::from_rust_string(
        env,
        format!(
            "{NOTICE_TITLE}\n本项目免费开源，请勿购买。\n\n项目地址\n{PROJECT_URL}\nQQ 交流群 1185712984\n\n游戏帮助\n{body}"
        ),
    );
    let _: () = msg![env; text_view setText:text];
    release(env, text);
}

fn finish_offline_farm_picker(env: &mut Environment, controller: id) {
    // On first open the guest sets its profile data before loading the view,
    // so its first reloadData can be sent to a nil table.
    let view: id = msg![env; controller view];
    let Some(table) = zombie_farm_read_object_ivar(env, controller, "profileTable") else {
        return;
    };
    let Some(back) = zombie_farm_read_object_ivar(env, controller, "backButton") else {
        return;
    };
    let white: id = msg_class![env; UIColor whiteColor];
    let dark: id = msg_class![env; UIColor colorWithWhite:0.22_f32 alpha:1.0_f32];
    let back_title = ns_string::get_static_str(env, "返回");
    let _: () = msg![env; back setBackgroundImage:nil forState:UIControlStateNormal];
    let _: () = msg![env; back setBackgroundColor:dark];
    let _: () = msg![env; back setTitle:back_title forState:UIControlStateNormal];
    let _: () = msg![env; back setTitleColor:white forState:UIControlStateNormal];
    let _: () = msg![env; back setHidden:false];
    let _: () = msg![env; view bringSubviewToFront:back];
    if let Some(banner) = zombie_farm_read_object_ivar(env, controller, "bannerLabel") {
        let _: () = msg![env; banner setTextColor:white];
    }

    let footer: id = msg![env; table tableFooterView];
    let subviews: id = msg![env; footer subviews];
    let online_button: id = msg![env; subviews firstObject];
    if zombie_farm_object_class_name(env, online_button) == Some("UIButton") {
        let unavailable = ns_string::get_static_str(env, "原版在线农场已停服");
        let _: () = msg![env; online_button setTitle:unavailable forState:UIControlStateNormal];
        let _: () = msg![env; online_button setTitleColor:white forState:UIControlStateNormal];
        let _: () = msg![env; online_button setUserInteractionEnabled:false];
        set_farm_picker_credit(env, footer, online_button);
    }
    let _: () = msg![env; table reloadData];
}

fn set_farm_picker_credit(env: &mut Environment, footer: id, online_button: id) {
    // The guest may supply its profiles repeatedly to the same table footer.
    const CREDIT_TAG: i32 = 0x5a464352;
    let existing: id = msg![env; footer viewWithTag:CREDIT_TAG];
    if existing != nil {
        return;
    }
    let mut footer_frame: CGRect = msg![env; footer frame];
    let button_frame: CGRect = msg![env; online_button frame];
    let y = button_frame.origin.y + button_frame.size.height;
    let frame = CGRect {
        origin: CGPoint { x: 0.0, y },
        size: CGSize {
            width: footer_frame.size.width,
            height: 20.0,
        },
    };
    footer_frame.size.height = footer_frame.size.height.max(y + frame.size.height);
    let _: () = msg![env; footer setFrame:footer_frame];
    let label: id = msg_class![env; UILabel alloc];
    let label: id = msg![env; label initWithFrame:frame];
    let font: id = msg_class![env; UIFont systemFontOfSize:11.0_f32];
    let color: id = msg_class![env; UIColor colorWithWhite:0.82_f32 alpha:1.0_f32];
    let credit = ns_string::get_static_str(env, "本整合版免费，项目地址见「设置 → 关于」");
    let _: () = msg![env; label setTag:CREDIT_TAG];
    let _: () = msg![env; label setTextAlignment:UITextAlignmentCenter];
    let _: () = msg![env; label setTextColor:color];
    let _: () = msg![env; label setFont:font];
    let _: () = msg![env; label setText:credit];
    let _: () = msg![env; footer addSubview:label];
    release(env, label);
}
