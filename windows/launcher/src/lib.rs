#![cfg(target_os = "android")]

use serde_json::{json, Value};
use tauri::{plugin::PluginHandle, Manager, State, Wry};

#[tauri::command]
async fn manager(
    host: State<'_, PluginHandle<Wry>>,
    action: String,
    data: Value,
) -> Result<Value, String> {
    host.run_mobile_plugin_async("dispatch", json!({ "action": action, "data": data }))
        .await
        .map_err(|error| error.to_string())
}

#[tauri::mobile_entry_point]
fn run() {
    tauri::Builder::default()
        .plugin(
            tauri::plugin::Builder::<Wry>::new("farm")
                .setup(|app, api| {
                    app.manage(api.register_android_plugin("org.touchhle.android", "ManagerPlugin")?);
                    Ok(())
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![manager])
        .run(tauri::generate_context!())
        .expect("Android manager failed to start");
}
