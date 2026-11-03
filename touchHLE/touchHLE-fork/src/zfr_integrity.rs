/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! 僵尸农场中文移植：内置 IPA 的完整性校验。
//!
//! 标题画面右上角的「本作免费开源 · 请勿购买」是画在 IPA 内的图片上的。只要
//! 换回一个干净的 IPA，这个水印就消失了 —— 所以启动前先核对：这次要运行的
//! 包，是不是官方发行的那一个。
//!
//! 这不是 DRM，也拦不住铁了心的人：能改 touchHLE 的人自然能删掉这处检查。
//! 它的作用是让「把官方包里的水印抹掉再转卖」至少需要反编译，而不是把文件
//! 改个名、换一份就完事。因此检查必须**失败即拒绝启动**，只是记一条日志没有
//! 意义。
//!
//! 发版时 [`OFFICIAL_IPA_SHA256`] 必须随 IPA 一起更新。忘了更新的话，新包会
//! 被自己的校验拦住；`_analysis\_build_release.ps1` 打包前会核对这里和实际上架
//! 的 IPA，对不上直接构建失败（见 `_check_pinned_hashes.ps1`）。

use sha2::{Digest, Sha256};
use std::io::Read;
use std::path::Path;

/// 官方发行包里那个 IPA 的 SHA-256 与字节数。
///
/// 当前对应 `Zombie Farm ZFR 1.0.zh-CN-complete-final.fixed-fonts-v29fix-notice.ipa`
/// （2026-11-02 发布，59,570,028 B）。
const OFFICIAL_IPA_SHA256: &str = "7bb214498b149e11deca49c19e5a21b9aa7f763646537206b85cbbab86582ffc";
const OFFICIAL_IPA_SIZE: u64 = 59_570_028;

pub const PROJECT_URL: &str = "https://github.com/Ashena1017/zombie-farm-touchhle-cn";

/// 逐块计算文件的 SHA-256，返回小写十六进制。
///
/// 分块读而不是 `read` 整个文件：IPA 有 59 MB，没必要在启动时多占一块内存。
fn sha256_of_file(path: &Path) -> Result<String, String> {
    let mut file =
        std::fs::File::open(path).map_err(|e| format!("打不开 {}：{e}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|e| format!("读取 {} 失败：{e}", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(hex, "{byte:02x}");
    }
    Ok(hex)
}

/// `SDL_MESSAGEBOX_ERROR`：SDL2 的 ABI 常量，rust-sdl2 的 `-sys` 绑定没有导出它，
/// 所以这里按 SDL 头文件里的数值写（0x00000010）。
const SDL_MESSAGEBOX_ERROR: u32 = 0x0000_0010;

/// 在 Windows 上用系统消息框把话说清楚。
///
/// touchHLE.exe 是控制台子系统程序，管理器又用 CreateNoWindow 启动它 —— 双击
/// 或从管理器启动时，只看 stderr 是看不到任何东西的，必须弹一个窗。
/// Android 上这个包由 APK 自带、安装时已经按同一个哈希校验过，走不到这里，
/// 所以不需要（也不适合）弹 SDL 的消息框。
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

/// 校验即将运行的 app bundle / IPA。
///
/// 只接受与官方发行版逐字节一致的 `.ipa`。目录形式的 `.app` 无法比较，一律
/// 拒绝 —— 官方发行物里只有 `.ipa`。
///
/// `ZFR_ALLOW_ANY_IPA=1` 可以跳过这项检查，留给开发和调试用（见 TECHNICAL.md）。
/// 刻意**不**在拒绝提示里提这个开关：那等于把绕过方法印在受害者面前。
pub fn verify_bundle_path(path: &Path) -> Result<(), String> {
    if std::env::var_os("ZFR_ALLOW_ANY_IPA").is_some() {
        log!("Warning: ZFR_ALLOW_ANY_IPA is set, skipping the official IPA check.");
        return Ok(());
    }

    let metadata = std::fs::metadata(path);
    let matches = match &metadata {
        Ok(meta) if meta.is_file() && meta.len() == OFFICIAL_IPA_SIZE => {
            match sha256_of_file(path) {
                Ok(hash) if hash == OFFICIAL_IPA_SHA256 => true,
                Ok(hash) => {
                    log!(
                        "Official IPA check failed: {} has sha256 {}, expected {}.",
                        path.display(),
                        hash,
                        OFFICIAL_IPA_SHA256
                    );
                    false
                }
                Err(e) => {
                    log!("Warning: {e}");
                    false
                }
            }
        }
        Ok(meta) if meta.is_file() => {
            log!(
                "Official IPA check failed: {} is {} bytes, expected {}.",
                path.display(),
                meta.len(),
                OFFICIAL_IPA_SIZE
            );
            false
        }
        _ => {
            log!(
                "Official IPA check failed: {} is not a regular .ipa file.",
                path.display()
            );
            false
        }
    };

    if matches {
        log!("Official Zombie Farm IPA verified (sha256 {}).", OFFICIAL_IPA_SHA256);
        return Ok(());
    }

    let message = format!(
        "这个游戏包不是官方发行版，已停止启动。\n\n\
         官方发行版里的 IPA 是固定的：标题画面右上角印着「本作免费开源 · 请勿购买」\
         和项目地址。\n\
         这次要运行的文件和官方版本对不上 —— 它可能被替换过，也可能被改过。\n\n\
         官方地址：{PROJECT_URL}\n\n\
         本软件完全免费、开源。如果你是花钱买的，请申请退款并向平台举报那条商品。"
    );
    // 控制台和消息框都留一份：管理器会抓 stderr 显示在状态栏里。
    log!("{}", message);
    show_blocking_message(&message);
    Err("这个游戏包不是官方发行版，已停止启动。".to_string())
}
