use serde_json::{json, Value};
use std::{
    ffi::OsStr,
    io::{BufRead, BufReader, Write},
    os::windows::process::CommandExt,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{Mutex, MutexGuard},
};
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

pub type Result<T> = std::result::Result<T, String>;

pub fn lock<T>(mutex: &Mutex<T>) -> Result<MutexGuard<'_, T>> {
    mutex
        .lock()
        .map_err(|_| "管理器状态读取失败，请重新打开。".into())
}

pub struct Layout {
    pub install: PathBuf,
    pub runtime: PathBuf,
    pub emulator: PathBuf,
    pub ipas: PathBuf,
}

impl Layout {
    pub fn detect() -> Result<Self> {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let install = exe.parent().ok_or("无法定位游戏目录。")?.to_owned();
        if install.join("RepositoryPaths.ps1").is_file() {
            let repo = install.parent().ok_or("无法定位项目目录。")?;
            let runtime = repo.join("run/windows");
            return Ok(Self {
                emulator: runtime.join("touchHLE"),
                ipas: repo.join("zombie_farm_ipa"),
                install,
                runtime,
            });
        }
        let nested = install.join("touchHLE");
        let emulator = if nested.join("touchHLE.exe").is_file() {
            nested
        } else {
            install.clone()
        };
        Ok(Self {
            ipas: install.join("zombie_farm_ipa"),
            runtime: install.clone(),
            install,
            emulator,
        })
    }

    fn powershell(&self, file: &str) -> Result<Command> {
        let script = self.install.join(file);
        if !script.is_file() {
            return Err(format!(
                "缺少管理器文件 {}，请完整解压 Windows 发行包。",
                script.display()
            ));
        }
        let system = std::env::var_os("SystemRoot").ok_or("找不到 Windows 系统目录。")?;
        let mut command =
            Command::new(Path::new(&system).join("System32/WindowsPowerShell/v1.0/powershell.exe"));
        command
            .args([
                "-NoLogo",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
            ])
            .arg(script)
            .current_dir(&self.install)
            .creation_flags(CREATE_NO_WINDOW);
        Ok(command)
    }

    pub fn fallback(&self) -> Result<()> {
        self.powershell("GameManager.ps1")?
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
}

pub struct Backend {
    pub layout: Layout,
    pub appearance_lock: Mutex<()>,
    worker: Mutex<Option<Worker>>,
}

impl Backend {
    pub fn new(layout: Layout) -> Self {
        Self {
            layout,
            appearance_lock: Mutex::new(()),
            worker: Mutex::new(None),
        }
    }

    pub fn warm(&self) -> Result<()> {
        let mut slot = lock(&self.worker)?;
        if slot.is_none() {
            *slot = Some(Worker::start(&self.layout)?);
        }
        Ok(())
    }

    pub fn request(&self, action: &str, data: Value) -> Result<Value> {
        let mut slot = lock(&self.worker)?;
        if slot.is_none() {
            *slot = Some(Worker::start(&self.layout)?);
        }
        let worker = slot.as_mut().unwrap();
        let result = worker.exchange(&json!({ "action": action, "data": data }));
        if result.is_err() {
            // A broken pipe may follow a successful disk write. Reconnect on the
            // next request, and never replay the failed request automatically.
            *slot = None;
        }
        let response = result?;
        if response["ok"] == true {
            Ok(response["value"].clone())
        } else {
            Err(response["error"].as_str().unwrap_or("操作失败。").into())
        }
    }
}

struct Worker {
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    _child: Child,
}

impl Worker {
    fn start(layout: &Layout) -> Result<Self> {
        let mut child = layout
            .powershell("ManagerWorker.ps1")?
            .env(
                "ZFR_MANAGER_EXECUTABLE",
                std::env::current_exe().map_err(|e| e.to_string())?,
            )
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("启动存档服务失败：{e}"))?;
        Ok(Self {
            stdin: child.stdin.take().ok_or("无法打开命令管道。")?,
            stdout: BufReader::new(child.stdout.take().ok_or("无法读取工作进程。")?),
            _child: child,
        })
    }

    fn exchange(&mut self, request: &Value) -> Result<Value> {
        serde_json::to_writer(&mut self.stdin, request).map_err(|e| e.to_string())?;
        self.stdin
            .write_all(b"\n")
            .and_then(|()| self.stdin.flush())
            .map_err(|e| e.to_string())?;
        let mut line = String::new();
        if self
            .stdout
            .read_line(&mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err(
                "工作进程意外退出，请确认 GameManager.ps1 和 ManagerWorker.ps1 均已完整解压。"
                    .into(),
            );
        }
        serde_json::from_str(line.trim_start_matches('\u{feff}'))
            .map_err(|e| format!("读取管理器结果失败：{e}"))
    }
}

pub fn package_check(backend: &Backend) -> Result<()> {
    if !backend.layout.install.join("GameOutput.cs").is_file() {
        return Err("缺少 GameOutput.cs，请完整解压便携包。".into());
    }
    if !backend.layout.install.join("compat/WinForms.ps1").is_file() {
        return Err("缺少兼容界面 compat/WinForms.ps1，请完整解压便携包。".into());
    }
    let state = backend.request("snapshot", Value::Null)?;
    if !state["settings"].is_object() || state["selected"].is_null() {
        return Err("未找到游戏或无法读取已有设置。".into());
    }
    let report = backend.request("verify", Value::Null)?;
    if report["level"] != "ok" {
        return Err(report["text"].as_str().unwrap_or("校验失败。").into());
    }
    Ok(())
}

pub fn check_requested() -> bool {
    std::env::args_os().nth(1).as_deref() == Some(OsStr::new("--check-package"))
}
