use crate::bridge::Result;
use sha2::{Digest, Sha256};
use std::{
    ffi::{OsStr, OsString},
    io,
    os::windows::ffi::{OsStrExt, OsStringExt},
    path::Path,
    ptr,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE, HWND, WAIT_ABANDONED, WAIT_OBJECT_0, WAIT_TIMEOUT},
    Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH},
    System::Threading::{CreateMutexW, ReleaseMutex, WaitForSingleObject},
    UI::{Controls::Dialogs::*, WindowsAndMessaging::*},
};

fn wide(value: &OsStr) -> Vec<u16> {
    value.encode_wide().chain(Some(0)).collect()
}

pub fn message(owner: HWND, body: &str, flags: u32) -> i32 {
    let text = wide(OsStr::new(body));
    let title = wide(OsStr::new("僵尸农场 · 游戏管理"));
    unsafe { MessageBoxW(owner, text.as_ptr(), title.as_ptr(), flags) }
}

pub fn choose_ipa(owner: HWND, initial: &Path) -> Result<Option<String>> {
    let directory = wide(initial.as_os_str());
    let title = wide(OsStr::new("选择游戏 IPA"));
    let filter = wide(OsStr::new("iOS 应用包 (*.ipa)\0*.ipa\0"));
    let mut path = vec![0u16; 32768];
    let mut options = OPENFILENAMEW {
        lStructSize: size_of::<OPENFILENAMEW>() as u32,
        hwndOwner: owner,
        lpstrTitle: title.as_ptr(),
        lpstrInitialDir: directory.as_ptr(),
        lpstrFilter: filter.as_ptr(),
        nFilterIndex: 1,
        lpstrFile: path.as_mut_ptr(),
        nMaxFile: path.len() as u32,
        Flags: OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST | OFN_EXPLORER,
        ..Default::default()
    };
    if unsafe { GetOpenFileNameW(&mut options) } == 0 {
        let code = unsafe { CommDlgExtendedError() };
        return if code == 0 {
            Ok(None)
        } else {
            Err(format!("无法打开文件选择窗口：{code:#x}"))
        };
    }
    let len = path.iter().position(|&c| c == 0).unwrap_or(path.len());
    Ok(Some(
        OsString::from_wide(&path[..len])
            .to_string_lossy()
            .into_owned(),
    ))
}

pub fn replace_file(source: &Path, target: &Path) -> Result<()> {
    let source = wide(source.as_os_str());
    let target = wide(target.as_os_str());
    let ok = unsafe {
        MoveFileExW(
            source.as_ptr(),
            target.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if ok == 0 {
        return Err(format!("保存外观失败：{}", io::Error::last_os_error()));
    }
    Ok(())
}

pub struct Instance(HANDLE);

impl Instance {
    pub fn acquire(emulator: &Path) -> Result<Option<Self>> {
        // Share the installed WinForms launcher's per-directory mutex name.
        let normalized = emulator.to_string_lossy().replace('/', "\\").to_lowercase();
        let hash = format!("{:X}", Sha256::digest(normalized.as_bytes()));
        let name = wide(OsStr::new(&format!(
            "Local\\ZombieFarmManager-{}",
            &hash[..16]
        )));
        let handle = unsafe { CreateMutexW(ptr::null(), 0, name.as_ptr()) };
        if handle.is_null() {
            return Err(io::Error::last_os_error().to_string());
        }
        match unsafe { WaitForSingleObject(handle, 0) } {
            WAIT_OBJECT_0 | WAIT_ABANDONED => Ok(Some(Self(handle))),
            code => {
                unsafe {
                    CloseHandle(handle);
                }
                if code == WAIT_TIMEOUT {
                    Ok(None)
                } else {
                    Err("无法检查管理器运行状态。".into())
                }
            }
        }
    }
}

impl Drop for Instance {
    fn drop(&mut self) {
        unsafe {
            ReleaseMutex(self.0);
            CloseHandle(self.0);
        }
    }
}
