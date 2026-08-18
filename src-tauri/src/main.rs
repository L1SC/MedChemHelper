#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const PORT: u16 = 8765;

struct Backend(Mutex<Option<Child>>);

fn backend_exe(app: &tauri::App) -> Result<std::path::PathBuf, String> {
    // 1) exe 同目录下的 backend 文件夹（免安装运行）
    let near_exe = std::env::current_exe()
        .ok()
        .and_then(|p| {
            p.parent()
                .map(|d| d.join("backend/ChemHelperBackend/ChemHelperBackend.exe"))
        })
        .filter(|p| p.exists());
    if let Some(p) = near_exe {
        eprintln!("[tauri] backend(exe旁): {}", p.display());
        return Ok(p);
    }
    // 2) 开发模式：src-tauri 上一级
    #[cfg(debug_assertions)]
    {
        let dev = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../backend/ChemHelperBackend/ChemHelperBackend.exe");
        if dev.exists() {
            eprintln!("[tauri] backend(开发): {}", dev.display());
            return Ok(dev);
        }
    }
    // 3) 打包后：资源目录
    app.path()
        .resolve(
            "backend/ChemHelperBackend/ChemHelperBackend.exe",
            tauri::path::BaseDirectory::Resource,
        )
        .map_err(|e| e.to_string())
}

fn wait_health(tries: u32) -> bool {
    for _ in 0..tries {
        if let Ok(mut s) = TcpStream::connect(("127.0.0.1", PORT)) {
            let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
            let req = format!(
                "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
                PORT
            );
            if s.write_all(req.as_bytes()).is_ok() {
                let mut buf = [0u8; 128];
                if s.read(&mut buf).is_ok() {
                    let text = String::from_utf8_lossy(&buf);
                    if text.contains(" 200 ") || text.contains("\"ok\"") {
                        return true;
                    }
                }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let exe = backend_exe(app)?;
            let child = Command::new(&exe)
                .args(["--port", &PORT.to_string(), "--no-browser"])
                .current_dir(exe.parent().unwrap_or_else(|| std::path::Path::new(".")))
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|e| format!("后端启动失败: {}", e))?;
            eprintln!("[tauri] 后端已生成, pid={}", child.id());
            app.manage(Backend(Mutex::new(Some(child))));

            let healthy = wait_health(60);
            eprintln!("[tauri] 后端健康检查: {}", healthy);
            let url = format!("http://127.0.0.1:{}/", PORT)
                .parse::<tauri::Url>()
                .map_err(|e| e.to_string())?;

            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("MedChemHelper")
                .inner_size(1400.0, 940.0)
                .min_inner_size(1000.0, 680.0)
                .build()?;
            eprintln!("[tauri] 窗口创建成功");
            let _ = window;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Backend>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
