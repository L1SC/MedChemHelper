# MedChemHelper-Tauri

药物化学学习工具：输入名称、分子式、SMILES 或 CAS，查询候选化合物、结构式、药理信息、官能团和相似药物。

## 当前结构

- `server.py`：本地 Python HTTP 后端，支持普通 JSON 和 NDJSON 流式检索。
- `static/`：Tauri 使用的前端页面。
- `data/`：药物、药理、中文词典、教材分类和官能团数据。
- `scripts/build_sar_diagrams.py`：按教材位点编号重建构效关系 SVG。
- `src-tauri/`：Tauri 2 桌面壳。

## 运行开发后端

```powershell
$env:MEDCHEMHELPER_DEV = "1"
python server.py --port 8765 --no-browser
```

然后访问 `http://127.0.0.1:8765/`。

## 构建桌面版

需要 Node.js、Rust、Python、PyInstaller 和 RDKit。执行统一构建脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_tauri.ps1
```

脚本会依次重建构效关系 SVG、PyInstaller 后端和 Tauri MSI。`CARGO_TARGET_DIR` 使用仓库外的 ASCII 路径，以兼容 Windows GNU 工具链对中文路径的处理限制。

## Release 格式

自 `v1.7.0` 起，GitHub Release 只发布 Windows MSI 安装包。不要再上传 ZIP、绿色版 EXE 或 NSIS 安装包；Tauri 配置也固定为仅构建 `msi` 目标。

## 数据来源

PubChem REST API、ChemToolsHub、RDKit，以及仓库内置的药物和药理知识库。

## 许可证

[MIT](LICENSE)
