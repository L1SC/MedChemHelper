$ErrorActionPreference = "Stop"
# Tauri 版打包脚本：打包后端 -> 部署到 Tauri 副本运行版 -> 生成发布 zip
$root = Split-Path -Parent $PSScriptRoot
$outputs = Split-Path -Parent $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$tauri = Join-Path $outputs "MedChemHelper-Tauri"
if (!(Test-Path $py)) { Write-Error "缺少 .venv 环境"; exit 1 }
if (!(Test-Path $tauri)) { Write-Error "缺少 Tauri 副本目录"; exit 1 }

Write-Host "[0/4] 预生成结构图（WebP）..."
& $py (Join-Path $PSScriptRoot "pregen_images.py")

Write-Host "[1/4] 打包后端 exe ..."
& $py -m PyInstaller --noconfirm --onedir --name ChemHelperBackend `
  --distpath (Join-Path $root "backend-dist") `
  --workpath (Join-Path $root "build-backend-tauri") `
  --specpath (Join-Path $root "scripts") `
  --add-data (Join-Path $root "static;static") `
  --add-data (Join-Path $root "data;data") `
  --collect-all rdkit `
  --exclude-module tkinter --exclude-module Tkinter --exclude-module _tkinter `
  --exclude-module tcl --exclude-module turtle `
  (Join-Path $root "server.py")

Write-Host "[2/4] 部署到 Tauri 运行版 ..."
$run = Join-Path $tauri "运行版\backend\ChemHelperBackend"
$bak = "$run.bak"
if (Test-Path $bak) { Remove-Item -LiteralPath $bak -Recurse -Force }
if (Test-Path $run) { Rename-Item -LiteralPath $run -NewName "ChemHelperBackend.bak" -Force }
Copy-Item -LiteralPath (Join-Path $root "backend-dist\ChemHelperBackend") -Destination $run -Recurse -Force
if (Test-Path $bak) { Remove-Item -LiteralPath $bak -Recurse -Force }

Write-Host "[3/4] 生成发布 zip ..."
$staging = Join-Path $tauri "MedChemHelper-Tauri-win32"
if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $tauri "运行版") -Destination $staging -Recurse
tar -a -c -f (Join-Path $tauri "MedChemHelper-Tauri-win32.zip") -C $tauri MedChemHelper-Tauri-win32
Remove-Item -LiteralPath $staging -Recurse -Force

Write-Host "完成：$tauri\MedChemHelper-Tauri-win32.zip"
