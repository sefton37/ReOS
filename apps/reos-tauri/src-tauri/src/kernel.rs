use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};

use serde_json::{json, Value};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum KernelError {
    #[error("kernel not started")]
    NotStarted,
    #[error("failed to spawn kernel: {0}")]
    SpawnFailed(String),
    #[error("failed to write to kernel stdin: {0}")]
    StdinWriteFailed(String),
    #[error("failed to read kernel stdout: {0}")]
    StdoutReadFailed(String),
    #[error("kernel returned invalid json: {0}")]
    InvalidJson(String),
    #[error("kernel process exited")]
    Exited,
}

pub struct KernelProcess {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: u64,
}

fn find_repo_venv_python() -> Option<PathBuf> {
    // Walk upward from the current executable looking for `.venv/bin/python`.
    // This makes `tauri dev` work reliably in a monorepo-style checkout.
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent()?.to_path_buf();

    for _ in 0..12 {
        let candidate = dir.join(".venv").join("bin").join("python");
        if candidate.is_file() {
            return Some(candidate);
        }
        if !dir.pop() {
            break;
        }
    }

    None
}

fn python_command() -> String {
    // Highest priority: explicit override.
    if let Ok(p) = std::env::var("REOS_PYTHON") {
        let p = p.trim();
        if !p.is_empty() {
            return p.to_string();
        }
    }

    // Next: auto-detect `.venv/bin/python`.
    if let Some(p) = find_repo_venv_python() {
        return p.to_string_lossy().to_string();
    }

    // Fallback: whatever is on PATH.
    "python".to_string()
}

impl KernelProcess {
    pub fn start() -> Result<Self, KernelError> {
        // Dev-mode: prefer REOS_PYTHON or a repo `.venv/bin/python`.
        // Packaging: likely ship a Python runtime or use a platform sidecar.
        let python = python_command();
        let mut child = Command::new(&python)
            .args(["-m", "reos.ui_rpc_server"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| KernelError::SpawnFailed(e.to_string()))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| KernelError::SpawnFailed("missing stdin".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| KernelError::SpawnFailed("missing stdout".to_string()))?;

        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_id: 1,
        })
    }

    pub fn request(&mut self, method: &str, params: Value) -> Result<Value, KernelError> {
        if let Some(status) = self.child.try_wait().map_err(|e| KernelError::Exited)? {
            let _ = status;
            return Err(KernelError::Exited);
        }

        let id = self.next_id;
        self.next_id += 1;

        let req = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params
        });

        let line = serde_json::to_string(&req).unwrap_or_else(|_| "{}".to_string());
        self.stdin
            .write_all(line.as_bytes())
            .and_then(|_| self.stdin.write_all(b"\n"))
            .and_then(|_| self.stdin.flush())
            .map_err(|e| KernelError::StdinWriteFailed(e.to_string()))?;

        // Read responses until we see the matching id.
        let mut buf = String::new();
        loop {
            buf.clear();
            let n = self
                .stdout
                .read_line(&mut buf)
                .map_err(|e| KernelError::StdoutReadFailed(e.to_string()))?;
            if n == 0 {
                return Err(KernelError::Exited);
            }

            let parsed: Value = serde_json::from_str(buf.trim())
                .map_err(|e| KernelError::InvalidJson(e.to_string()))?;

            let resp_id = parsed.get("id");
            if resp_id == Some(&Value::Number(id.into())) {
                return Ok(parsed);
            }
        }
    }
}
