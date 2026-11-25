/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Check the IPA shipped with the distribution independently of the selected game.

include!(concat!(env!("OUT_DIR"), "/zfr_release.rs"));

pub const PROJECT_URL: &str = "https://github.com/Ashena1017/zombie-farm-touchhle-cn";

#[cfg(not(target_os = "android"))]
pub fn warn_if_bundled_ipa_changed() {
    use std::{ffi::CString, fs::File, io};

    use sha2::{Digest, Sha256};

    if std::env::var("ZFR_MANAGER_IPA_CHECKED").as_deref() == Ok("1")
        || std::env::var("ZFR_ALLOW_ANY_IPA").as_deref() == Ok("1")
    {
        return;
    }

    let check = || -> io::Result<bool> {
        // Both the portable release and the repository runtime keep the
        // official game directory next to the emulator's directory.
        let exe = std::env::current_exe()?;
        let path = exe
            .with_file_name("..")
            .join("zombie_farm_ipa")
            .join(OFFICIAL_IPA_NAME);
        let mut file = File::open(path)?;
        let meta = file.metadata()?;
        if !meta.is_file() || meta.len() != OFFICIAL_IPA_SIZE {
            return Ok(false);
        }
        let mut hash = Sha256::new();
        io::copy(&mut file, &mut hash)?;
        Ok(format!("{:x}", hash.finalize()) == OFFICIAL_IPA_SHA256)
    };
    let reason = match check() {
        Ok(true) => return,
        Ok(false) => "内置 IPA 的内容与官方发行版不一致。",
        Err(e) if e.kind() == io::ErrorKind::NotFound => "未找到官方发行版的内置 IPA。",
        Err(e) => {
            log!("Could not check bundled IPA: {e}");
            "无法读取官方发行版的内置 IPA。"
        }
    };
    let message = format!(
        "{reason} 你拿到的可能是改版或不完整的整合包。\n\n\
         本整合版免费，官方地址：{PROJECT_URL}\n\n关闭提示后可继续使用你选择的游戏。"
    );
    log!("{}", message);
    let title = CString::new("僵尸农场 · 内置游戏包校验").unwrap();
    let body = CString::new(message).unwrap();
    // SDL_MESSAGEBOX_WARNING, available before SDL_Init.
    unsafe {
        sdl2_sys::SDL_ShowSimpleMessageBox(
            0x20,
            title.as_ptr(),
            body.as_ptr(),
            std::ptr::null_mut(),
        );
    }
}
