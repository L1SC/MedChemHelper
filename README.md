# MedChemHelper

化学学习工具：输入名称 / 分子式 / SMILES / CAS，快速得到候选化合物、结构式、药理信息与相似药物。

## 功能特性

- **检索**：中文名（内置 614 种药物 + 常用化合物词典）、英文名（PubChem 联想/部分匹配）、分子式（列出同分异构体）、SMILES、CAS
- **结构式**：ChemToolsHub 渲染 2D 结构图，离线自动降级为 RDKit 本地渲染
- **药理信息**：约 190 种常见药物精编资料（母体、药效基团、靶点、药理作用、代谢毒理、相似药、部分构效关系 SAR），其余药物从 PubChem 提取兜底
- **官能团**：RDKit 自动识别 49 种基团/药物母核（β-内酰胺、1,4-二氢吡啶、苯二氮䓬、噻嗪、甾体、嘌呤、喹诺酮等），含药效基团信息
- **对比**：固定对比栏，检索下一个药物时并排比对；相似化合物显示中文名与共同结构
- **搜索体验**：同音模糊搜索（噁唑/恶唑、苯二氮卓/苯二氮䓬）；联网开关（离线仅用本地词典与本地渲染）

## 快速开始

### 网页版

双击 `启动工具.bat`，首次运行自动创建独立 Python 环境并安装 RDKit，然后打开浏览器访问 `http://127.0.0.1:8765/`。

手动启动：

```bat
.venv\Scripts\python server.py --port 8765
```

### 桌面版（独立窗口）

`desktop\dist\ChemHelper-win32-x64\ChemHelper.exe`（或 `desktop\dist\化学结构速查助手-独立版.zip` 解压即用），无需安装 Python。

## 数据与依赖

- 检索与属性数据：[PubChem REST API](https://pubchem.ncbi.nlm.nih.gov/)（在线）
- 结构图渲染：[ChemToolsHub](https://chemtoolshub.com/zh-hans/tools/molecular-descriptor-calculator/)（在线）
- 本地官能团识别与渲染备用：RDKit
- 工具本身不使用 AI，不消耗 tokens

## 目录结构

```text
chem-helper/
├─ server.py                 # 本地后端服务
├─ start.bat / 启动工具.bat   # 网页版一键启动
├─ static/                   # 前端页面
├─ data/                     # 药物库 / 药理信息 / 官能团库 / 中文词典
├─ scripts/                  # 药物库构建脚本
├─ desktop/                  # 桌面版（Electron 壳 + 打包脚本）
└─ images/                   # 结构图缓存（运行时生成）
```

## 常见问题

- **端口被占用**：`start.bat 8766` 或 `.venv\Scripts\python server.py --port 8766`
- **显示“未找到”**：中文名用常见叫法；英文支持部分匹配；也可用分子式（`C2H6O`）、SMILES（`CCO`）或 CAS 号
- **想添加更多药物**：编辑 `data/drug_names.csv` 后运行 `.venv\Scripts\python scripts\build_drugs.py` 重建
- **重新打包桌面版**：运行 `desktop\build-all.ps1`（需要 Node 环境）

## 许可证

[MIT](LICENSE)
