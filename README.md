# MedChemHelper-Tauri

药物化学学习工具：输入名称、分子式、SMILES 或 CAS，查询候选化合物、结构式、药理信息、官能团和相似药物。

## 当前结构

- `server.py`：本地 Python HTTP 后端，支持普通 JSON 和 NDJSON 流式检索。
- `static/`：Tauri 使用的前端页面。
- `data/`：药物、药理、中文词典和官能团数据。
- `backend/ChemHelperBackend/`：PyInstaller 后端运行包。
- `src-tauri/`：Tauri 2 桌面壳。
- `MedChemHelper.exe`：绿色版桌面程序，位于本体根目录。
- `WebView2Loader.dll`：桌面程序依赖的 WebView2 加载组件。
- `发行包/`（本体同级）：存放用于 GitHub Release 的压缩包。

## 运行开发后端

```powershell
$env:MEDCHEMHELPER_DEV = "1"
python server.py --port 8765 --no-browser
```

然后访问 `http://127.0.0.1:8765/`。

## 构建桌面版

需要 Node.js、Rust、Tauri CLI、Python、PyInstaller 和 RDKit。构建 Tauri 壳：

```powershell
$env:CARGO_TARGET_DIR = Join-Path (Split-Path -Parent (Get-Location)) "build-target"
npx --yes @tauri-apps/cli@2.11.4 build
```

`CARGO_TARGET_DIR` 使用项目根目录下的 ASCII 路径，是为了兼容 Windows GNU 工具链对中文路径的处理限制。后端运行包必须使用同一份 `server.py`、`static/` 和 `data/` 重新打包，否则发布版会继续使用旧的内嵌数据或前端文件。

## 数据来源

PubChem REST API、ChemToolsHub、RDKit，以及仓库内置的药物和药理知识库。

## 许可证

[MIT](LICENSE)
