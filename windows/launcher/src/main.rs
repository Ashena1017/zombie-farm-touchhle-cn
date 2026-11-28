#![windows_subsystem = "windows"]

mod appearance;
mod bridge;
mod win;

use appearance::Appearance;
use bridge::{lock, Backend, Layout, Result};
use serde_json::{json, Value};
use std::{ptr, sync::Arc, thread, time::Duration};
use tauri::{AppHandle, Emitter, Manager};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    IDYES, MB_ICONERROR, MB_ICONINFORMATION, MB_ICONWARNING, MB_OK, MB_YESNO,
};

fn show_manager(window: &tauri::WebviewWindow) {
    let _ = window.show();
    let _ = window.set_focus();
}

fn monitor_game(app: AppHandle, backend: Arc<Backend>) {
    thread::spawn(move || {
        let Some(window) = app.get_webview_window("main") else {
            return;
        };
        loop {
            thread::sleep(Duration::from_millis(800));
            let status = match backend.request("gameStatus", Value::Null) {
                Ok(status) => status,
                Err(error) => json!({"done": true, "error": true, "message": error}),
            };
            if status["stalled"] == true {
                show_manager(&window);
                let owner = window.hwnd().map(|h| h.0).unwrap_or(ptr::null_mut());
                if win::message(
                    owner,
                    status["message"].as_str().unwrap_or_default(),
                    MB_YESNO | MB_ICONWARNING,
                ) == IDYES
                {
                    let _ = backend.request("stopStalled", Value::Null);
                }
                let _ = window.hide();
            }
            if status["done"] == true {
                show_manager(&window);
                let _ = app.emit_to("main", "game-exit", &status);
                return;
            }
        }
    });
}

fn dispatch(app: AppHandle, action: &str, data: Value) -> Result<Value> {
    let state = app.state::<Arc<Backend>>();
    let backend = state.inner();
    let window = app.get_webview_window("main").ok_or("找不到管理器窗口。")?;
    match action {
        "appearance" | "setAppearance" => {
            let _guard = lock(&backend.appearance_lock)?;
            let appearance = if action == "setAppearance" {
                let settings: Appearance =
                    serde_json::from_value(data).map_err(|_| "外观设置格式无效。")?;
                settings.save(&backend.layout.runtime)?;
                settings
            } else {
                Appearance::load(&backend.layout.runtime)
            };
            window
                .set_theme(appearance.native_theme())
                .map_err(|e| e.to_string())?;
            let mut result = serde_json::to_value(appearance).map_err(|e| e.to_string())?;
            result["notice"] = json!(std::env::var("ZFR_MANAGER_NO_NOTICE").as_deref() != Ok("1"));
            Ok(result)
        }
        "browseIpa" => {
            let owner = window.hwnd().map_err(|e| e.to_string())?.0;
            match win::choose_ipa(owner, &backend.layout.ipas)? {
                Some(path) => backend.request("selectIpa", json!({ "path": path })),
                None => backend.request("snapshot", Value::Null),
            }
        }
        "launch" => {
            let result = backend.request("launch", data)?;
            if result["started"] == true {
                let _ = window.hide();
                monitor_game(app.clone(), Arc::clone(backend));
            }
            Ok(result)
        }
        "snapshot" | "selectIpa" | "setSetting" | "resetTime" | "setCurrency" | "backup" | "restore"
        | "resetFarm" | "delete" | "verify" | "openProject" | "openSaves" => backend.request(action, data),
        _ => Err("未知的管理器操作。".into()),
    }
}

#[tauri::command]
async fn manager(app: AppHandle, action: String, data: Value) -> Result<Value> {
    tauri::async_runtime::spawn_blocking(move || dispatch(app, &action, data))
        .await
        .map_err(|e| e.to_string())?
}

fn run() -> Result<()> {
    let backend = Arc::new(Backend::new(Layout::detect()?));
    if bridge::check_requested() {
        return bridge::package_check(&backend);
    }
    if tauri::webview_version().is_err() {
        win::message(ptr::null_mut(), "未检测到 Microsoft Edge WebView2 运行时，将打开兼容界面。安装 WebView2 后即可使用新版外观。", MB_OK | MB_ICONINFORMATION);
        return backend.layout.fallback();
    }
    let Some(instance) = win::Instance::acquire(&backend.layout.emulator)? else {
        win::message(
            ptr::null_mut(),
            "这个目录的游戏管理器已经打开了。",
            MB_OK | MB_ICONINFORMATION,
        );
        return Ok(());
    };
    // Start the storage process in parallel with WebView2 creation. Initial HTML,
    // navigation, appearance and first paint never wait on storage or SHA-256.
    let worker = Arc::clone(&backend);
    thread::spawn(move || {
        let _ = worker.warm();
    });
    let app = tauri::Builder::default()
        .manage(Arc::clone(&backend))
        .invoke_handler(tauri::generate_handler![manager])
        .build(tauri::generate_context!());
    match app {
        Ok(app) => {
            app.run(|_, _| {});
            Ok(())
        }
        Err(error) => {
            drop(instance);
            win::message(
                ptr::null_mut(),
                &format!("无法打开 WebView2 界面，将使用兼容界面。\n{error}"),
                MB_OK | MB_ICONWARNING,
            );
            backend.layout.fallback()
        }
    }
}

fn main() {
    if let Err(error) = run() {
        if bridge::check_requested() {
            eprintln!("{error}");
        } else {
            win::message(ptr::null_mut(), &error, MB_OK | MB_ICONERROR);
        }
        std::process::exit(1);
    }
}
