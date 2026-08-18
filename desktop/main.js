const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const PORT = Number(process.env.CHEMHELPER_PORT || 8765);
const SMOKE_FILE = process.env.CHEMHELPER_SMOKE_FILE || "";

let backendProc = null;
let win = null;

function backendExe() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "ChemHelperBackend", "ChemHelperBackend.exe");
  }
  return path.join(__dirname, "dist-backend", "ChemHelperBackend", "ChemHelperBackend.exe");
}

function waitForHealth(triesLeft, cb) {
  const req = http.get(
    { host: "127.0.0.1", port: PORT, path: "/api/health", timeout: 2000 },
    (res) => {
      res.resume();
      if (res.statusCode === 200) return cb(true);
      retry();
    }
  );
  req.on("error", retry);
  req.on("timeout", () => { req.destroy(); retry(); });
  function retry() {
    if (triesLeft <= 0) return cb(false);
    setTimeout(() => waitForHealth(triesLeft - 1, cb), 500);
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400,
    height: 940,
    minWidth: 1000,
    minHeight: 680,
    autoHideMenuBar: true,
    title: "MedChemHelper",
    icon: path.join(__dirname, "assets", "icon.ico"),
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  win.loadURL(`http://127.0.0.1:${PORT}/`);
  win.webContents.on("did-finish-load", () => {
    if (SMOKE_FILE) {
      try { fs.writeFileSync(SMOKE_FILE, "ok"); } catch (e) { console.error(e); }
      setTimeout(() => app.quit(), 500);
    }
  });
  win.on("closed", () => { win = null; });
}

function startBackend() {
  const exe = backendExe();
  backendProc = spawn(exe, ["--port", String(PORT), "--no-browser"], {
    cwd: path.dirname(exe),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backendProc.stdout.on("data", (d) => console.log("[backend]", String(d).trim()));
  backendProc.stderr.on("data", (d) => console.error("[backend]", String(d).trim()));
  backendProc.on("exit", (code) => console.log("[backend] exited", code));

  waitForHealth(60, (ok) => {
    if (!ok) console.error("[backend] 未能启动，尝试直接连接已有服务…");
    createWindow();
  });
}

app.whenReady().then(() => {
  startBackend();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (backendProc) { try { backendProc.kill(); } catch (e) {} }
  app.quit();
});

app.on("will-quit", () => {
  if (backendProc) { try { backendProc.kill(); } catch (e) {} }
});
