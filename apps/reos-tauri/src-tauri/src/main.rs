#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod kernel;

use kernel::{KernelError, KernelProcess};
use serde_json::Value;
use std::sync::Mutex;

use tauri::State;

struct KernelState(Mutex<Option<KernelProcess>>);

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
fn kernel_request(state: State<'_, KernelState>, method: String, params: Value) -> Result<Value, String> {
    let mut guard = state.0.lock().map_err(|_| "lock poisoned".to_string())?;
    if guard.is_none() {
        let proc = KernelProcess::start().map_err(|e| e.to_string())?;
        *guard = Some(proc);
    }

    let proc = guard.as_mut().ok_or_else(|| KernelError::NotStarted.to_string())?;
    proc.request(&method, params).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .manage(KernelState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![kernel_start, kernel_request])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
