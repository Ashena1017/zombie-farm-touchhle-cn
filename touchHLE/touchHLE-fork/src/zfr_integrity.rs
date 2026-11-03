/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! 僵尸农场中文移植：官方发行版自带的那个 IPA 还在不在。
//!
//! 标题画面右上角的「本作免费开源 · 请勿购买」是画在 IPA 内的图片上的。最省事
//! 的偷法是：把官方包里那个 IPA 删掉，换一个干净的进去，再把整个文件夹转卖。
//! 所以启动前先确认**官方那个 IPA 还在原地**。
//!
//! 这一道**不比对哈希、也不限制你运行哪个包**：运行别的 IPA（自己的备份、
//! 别的版本、调试用的自制包）是正常需求，官方包还在就随你跑。内容有没有被改，
//! 由管理器的「文件校验」页和发布说明里的 SHA-256 负责。换句话说：
//!
//!   官方包被删 → 拒绝启动；官方包在、内容被换 → 照常启动，但管理器会标红。
//!
//! 这不是 DRM，也拦不住铁了心的人：能改 touchHLE 的人自然能删掉这处检查。
//! 它的作用是让「删掉带水印的包再转卖」不能靠拖拽完成。
//!
//! `ZFR_ALLOW_ANY_IPA=1` 可以跳过这项检查，留给开发和调试用（见 TECHNICAL.md）。
//! 刻意**不**在拒绝提示里提这个开关：那等于把绕过方法印在受害者面前。

use std::path::PathBuf;

/// 官方发行包里那个 IPA 的文件名。Windows 与 Android 的名字不同：
/// Android 侧的资产名被 `ZfStorage` / `ZfIpa` 按文件名匹配，是冻结的短名。
#[cfg(not(target_os = "android"))]
const OFFICIAL_IPA_NAME: &str =
    "Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa";
#[cfg(target_os = "android")]
const OFFICIAL_IPA_NAME: &str = "Zombie_Farm_v29fix.ipa";

/// 官方 IPA 的字节数。只比大小、不读内容 —— 这一道只管「还在不在」。
const OFFICIAL_IPA_SIZE: u64 = 59_570_028;

pub const PROJECT_URL: &str = "https://github.com/Ashena1017/zombie-farm-touchhle-cn";

/// `SDL_MESSAGEBOX_ERROR`：SDL2 的 ABI 常量，rust-sdl2 的 `-sys` 绑定没有导出它，
/// 所以这里按 SDL 头文件里的数值写（0x00000010）。
#[cfg(not(target_os = "android"))]
const SDL_MESSAGEBOX_ERROR: u32 = 0x0000_0010;

/// 在 Windows 上用系统消息框把话说清楚。
///
/// touchHLE.exe 是控制台子系统程序，管理器又用 CreateNoWindow 启动它 —— 双击
/// 或从管理器启动时，只看 stderr 是看不到任何东西的，必须弹一个窗。
/// Android 上这个包由 APK 自带、安装时按哈希校验过，走不到这里。
#[cfg(not(target_os = "android"))]
fn show_blocking_message(message: &str) {
    use std::ffi::CString;

    let Ok(title) = CString::new("僵尸农场 · 无法启动") else {
        return;
    };
    let Ok(body) = CString::new(message) else {
        return;
    };
    // 直接调 SDL 的简单消息框：它不要求 SDL_Init 先跑过，失败也只是返回错误码，
    // 不会 panic —— 在这里，弹不出窗也好过让启动流程崩掉。
    unsafe {
        sdl2_sys::SDL_ShowSimpleMessageBox(
            SDL_MESSAGEBOX_ERROR,
            title.as_ptr(),
            body.as_ptr(),
            std::ptr::null_mut(),
        );
    }
}

#[cfg(target_os = "android")]
fn show_blocking_message(_message: &str) {}

/// 官方 IPA 可能存在的所有位置。
///
/// 发行包和开发树的布局都是「`touchHLE\` 与 `zombie_farm_ipa\` 平级」，所以
/// 相对于工作目录和可执行文件目录各试一次 `zombie_farm_ipa\`，再各试一次
/// `..\zombie_farm_ipa\`，覆盖两种摆法。Android 侧用固定安装目录。
fn candidate_paths() -> Vec<PathBuf> {
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        bases.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            bases.push(dir.to_path_buf());
        }
    }

    let mut out: Vec<PathBuf> = Vec::new();
    for base in &bases {
        for relative in ["zombie_farm_ipa", "../zombie_farm_ipa"] {
            let candidate = base.join(relative).join(OFFICIAL_IPA_NAME);
            if !out.contains(&candidate) {
                out.push(candidate);
            }
        }
    }

    #[cfg(target_os = "android")]
    {
        let installed = crate::paths::user_data_base_path()
            .join(crate::paths::APPS_DIR)
            .join(OFFICIAL_IPA_NAME);
        if !out.contains(&installed) {
            out.push(installed);
        }
    }

    out
}

/// 校验官方 IPA 是否仍在原位。
///
/// 只看「有没有这个文件」：允许运行任何 IPA，包括用户自己的；但官方那个包
/// 不见了就拒绝启动，因为那已经不是本项目发布的那个文件夹了。
pub fn verify_official_ipa_present() -> Result<(), String> {
    if std::env::var_os("ZFR_ALLOW_ANY_IPA").is_some() {
        log!("Warning: ZFR_ALLOW_ANY_IPA is set, skipping the bundled-IPA check.");
        return Ok(());
    }

    let candidates = candidate_paths();
    if let Some(path) = candidates.iter().find(|p| p.is_file()) {
        match std::fs::metadata(path) {
            Ok(meta) if meta.len() == OFFICIAL_IPA_SIZE => {
                log!("Bundled Zombie Farm IPA present: {}", path.display());
            }
            Ok(meta) => {
                // 不拦：用户可能自己重打了包。管理器会按哈希把这件事标红。
                log!(
                    "Warning: bundled IPA at {} is {} bytes, expected {}; it looks replaced.",
                    path.display(),
                    meta.len(),
                    OFFICIAL_IPA_SIZE
                );
            }
            Err(e) => log!("Warning: {e}"),
        }
        return Ok(());
    }

    let message = format!(
        "官方发行版自带的那个游戏包不在了，已停止启动。\n\n\
         官方发行版的 zombie_farm_ipa 文件夹里应该有一个固定版本的 IPA，\
         标题画面右上角印着「本作免费开源 · 请勿购买」。\n\
         这次在原来的位置没有找到它 —— 可能被删掉了，也可能整个文件夹被挪过。\n\n\
         官方地址：{PROJECT_URL}\n\n\
         用别的 IPA 启动本身没有问题；把官方那个包放回 zombie_farm_ipa 文件夹就可以继续。\n\
         本软件完全免费、开源，如果你是花钱买的，请申请退款并向平台举报那条商品。"
    );
    // 控制台和消息框都留一份：管理器会抓 stderr 显示在状态栏里。
    log!("{}", message);
    show_blocking_message(&message);
    Err("官方发行版自带的游戏包不在了，已停止启动。".to_string())
}
