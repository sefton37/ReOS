#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod kernel;

use kernel::{KernelError, KernelProcess};
use serde_json::Value;
use std::sync::{Arc, Mutex};

use tauri::State;

struct KernelState(Arc<Mutex<Option<KernelProcess>>>);

#[tauri::command]
fn kernel_start(state: State<'_, KernelState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|_| "lock poisoned".to_string())?;
    if guard.is_some() {
        return Ok(());
    }
    let proc = KernelProcess::start().map_err(|e| e.to_string())?;
    *guard = Some(proc);
    Ok(())
}

#[tauri::command]
async fn kernel_request(state: State<'_, KernelState>, method: String, params: Value) -> Result<Value, String> {
    // IMPORTANT: The Python RPC is blocking I/O (stdin/stdout). If we do it on
    // Tauri's main thread, the WebView can miss paints, which feels like UI lag.
    // Offload to a background thread so the user message + thinking bubble
    // render immediately.
    let state = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut guard = state.lock().map_err(|_| "lock poisoned".to_string())?;
        if guard.is_none() {
            let proc = KernelProcess::start().map_err(|e| e.to_string())?;
            *guard = Some(proc);
        }

        let proc = guard.as_mut().ok_or_else(|| KernelError::NotStarted.to_string())?;
        proc.request(&method, params).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| format!("kernel_request join error: {e}"))?
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(KernelState(Arc::new(Mutex::new(None))))
        .invoke_handler(tauri::generate_handler![kernel_start, kernel_request])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
