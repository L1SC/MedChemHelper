$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) { $python = "python" }

$backendDist = Join-Path $root "backend"
$buildRoot = Join-Path $root ".build"
$cargoTarget = Join-Path (Split-Path -Parent $root) "build-target"
$tauriConfig = Get-Content -Raw (Join-Path $root "src-tauri\tauri.conf.json") | ConvertFrom-Json
$version = $tauriConfig.version

Write-Host "[1/3] 重建教材构效关系 SVG..."
& $python (Join-Path $PSScriptRoot "build_sar_diagrams.py")

Write-Host "[2/3] 打包 Python 后端..."
& $python -m PyInstaller --noconfirm --clean --onedir --name ChemHelperBackend `
  --distpath $backendDist `
  --workpath (Join-Path $buildRoot "backend-work") `
  --specpath (Join-Path $buildRoot "backend-spec") `
  --add-data "$(Join-Path $root 'static');static" `
  --add-data "$(Join-Path $root 'data');data" `
  --collect-all rdkit `
  --exclude-module tkinter --exclude-module Tkinter --exclude-module _tkinter `
  --exclude-module tcl --exclude-module turtle `
  (Join-Path $root "server.py")

Write-Host "[3/3] 构建 MSI..."
$env:CARGO_TARGET_DIR = $cargoTarget
Push-Location $root
try {
  npx --yes @tauri-apps/cli@2.11.4 build
} finally {
  Pop-Location
}

$msi = Join-Path $cargoTarget "release\bundle\msi\MedChemHelper_${version}_x64_en-US.msi"
if (!(Test-Path -LiteralPath $msi)) { throw "MSI 未生成：$msi" }
Write-Host "完成：$msi"
