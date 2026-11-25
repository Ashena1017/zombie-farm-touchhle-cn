/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Presentation of the single-button UIAlertView created by OptionsMenu.aboutTapped.

use super::{id, nil, release};
use crate::frameworks::core_graphics::{CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_string;
use crate::frameworks::uikit::ui_font::UITextAlignmentCenter;
use crate::frameworks::uikit::ui_view::ui_control::{
    ui_button::UIButtonTypeRoundedRect, UIControlEventTouchUpInside, UIControlStateNormal,
};
use crate::zfr_integrity::PROJECT_URL;
use crate::{msg, msg_class, Environment};

fn rect(x: f32, y: f32, width: f32, height: f32) -> CGRect {
    CGRect { origin: CGPoint { x, y }, size: CGSize { width, height } }
}

pub(crate) fn present(env: &mut Environment, alert: id, title: &str, message: &str, button_title: &str) -> bool {
    let Some((thread, controller)) = env.objc.zfr_about_presenter else { return false };
    if thread != env.current_thread {
        return false;
    }
    let scroll: id = msg![env; controller scrollView];
    let root: id = msg![env; scroll superview];
    if root == nil {
        return false;
    }
    let bounds: CGRect = msg![env; root bounds];
    let settings: CGRect = msg![env; scroll frame];
    let width = (settings.size.width - 32.0).min(398.0);
    let height = 258.0;
    let x = (settings.origin.x - bounds.origin.x + (settings.size.width - width) * 0.5).round();
    let y = (settings.origin.y - bounds.origin.y + (settings.size.height - height) * 0.5).round();
    let mask: id = msg_class![env; UIView alloc];
    let mask: id = msg![env; mask initWithFrame:bounds];
    let scrim: id = msg_class![env; UIColor colorWithWhite:0.0_f32 alpha:0.55_f32];
    let panel: id = msg_class![env; UIColor colorWithRed:0.13_f32 green:0.16_f32 blue:0.25_f32 alpha:1.0_f32];
    let community: id = msg_class![env; UIColor colorWithRed:0.17_f32 green:0.31_f32 blue:0.31_f32 alpha:1.0_f32];
    let white: id = msg_class![env; UIColor whiteColor];
    let _: () = msg![env; mask setBackgroundColor:scrim];
    let _: () = msg![env; alert setFrame:(rect(x, y, width, height))];
    let _: () = msg![env; alert setBackgroundColor:panel];
    let layer: id = msg![env; alert layer];
    let _: () = msg![env; layer setCornerRadius:8.0_f32];

    let mut label = |y, h, text: &str, size: f32, bold, band: id, lines: i32| {
        let view: id = msg_class![env; UILabel alloc];
        let view: id = msg![env; view initWithFrame:(rect(8.0, y, width - 16.0, h))];
        let font: id = if bold {
            msg_class![env; UIFont boldSystemFontOfSize:size]
        } else {
            msg_class![env; UIFont systemFontOfSize:size]
        };
        let text = ns_string::from_rust_string(env, text.to_owned());
        let _: () = msg![env; view setFont:font];
        let _: () = msg![env; view setTextColor:white];
        let _: () = msg![env; view setTextAlignment:UITextAlignmentCenter];
        let _: () = msg![env; view setNumberOfLines:lines];
        let _: () = msg![env; view setBackgroundColor:band];
        let _: () = msg![env; view setText:text];
        let _: () = msg![env; alert addSubview:view];
        release(env, text);
        release(env, view);
    };
    label(6.0, 26.0, &format!("游戏原作 · {title}"), 17.0, true, nil, 1);
    label(33.0, 70.0, message, 14.0, false, nil, 0);
    label(109.0, 24.0, "中文整合与维护", 15.0, true, community, 1);
    label(136.0, 22.0, "本整合版由社区独立维护，免费开源，请勿购买。", 14.0, false, nil, 1);
    label(160.0, 20.0, PROJECT_URL, 13.0, false, nil, 1);
    label(183.0, 20.0, "QQ 交流群　1185712984", 14.0, false, nil, 1);

    let button: id = msg_class![env; UIButton buttonWithType:UIButtonTypeRoundedRect];
    let text = ns_string::from_rust_string(env, button_title.to_owned());
    let _: () = msg![env; button setTitle:text forState:UIControlStateNormal];
    release(env, text);
    let _: () = msg![env; button setFrame:(rect(12.0, 210.0, width - 24.0, 40.0))];
    let _: () = msg![env; button layoutSubviews];
    let class = env.objc.get_known_class("UIAlertView", &mut env.mem);
    let action = env.objc.lookup_selector("_touchHLE_confirmAbout:").unwrap();
    let _: () = msg![env; button addTarget:class action:action forControlEvents:UIControlEventTouchUpInside];
    let _: () = msg![env; alert addSubview:button];
    let _: () = msg![env; mask addSubview:alert];
    let _: () = msg![env; root addSubview:mask];
    release(env, mask);
    true
}
