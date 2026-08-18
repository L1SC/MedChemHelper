$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$node = Join-Path $env:LOCALAPPDATA "..\..\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if (!(Test-Path $node)) {
  $node = (Get-Command node -ErrorAction SilentlyContinue).Source
}
if (!(Test-Path $py) -or !(Test-Path $node)) {
  Write-Error "需要工具目录下的 .venv 与 node 环境"
  exit 1
}

Write-Host "[1/4] 打包后端 exe ..."
& $py -m PyInstaller --noconfirm --onedir --name ChemHelperBackend `
  --distpath (Join-Path $PSScriptRoot "dist-backend") `
  --workpath (Join-Path $PSScriptRoot "build-backend") `
  --specpath $PSScriptRoot `
  --add-data (Join-Path $root "static;static") `
  --add-data (Join-Path $root "data;data") `
  --collect-all rdkit `
  (Join-Path $root "server.py")

Write-Host "[2/4] 生成图标 ..."
& $py -c @"
from PIL import Image, ImageDraw, ImageFont
import os
base = r'$PSScriptRoot\assets'
os.makedirs(base, exist_ok=True)
img = Image.new('RGBA', (256, 256), (37, 99, 235, 255))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, 248, 248], radius=48, fill=(37, 99, 235, 255), outline=(255, 255, 255, 255), width=6)
f = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 150)
t = '化'
bbox = d.textbbox((0, 0), t, font=f)
d.text(((256 - (bbox[2]-bbox[0]))/2 - bbox[0], (256 - (bbox[3]-bbox[1]))/2 - bbox[1]), t, font=f, fill=(255,255,255,255))
img.save(os.path.join(base, 'icon.ico'), sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon ok')
"@

Write-Host "[3/4] 准备 Electron 运行时 ..."
if (!(Test-Path (Join-Path $PSScriptRoot "node_modules\electron\dist\electron.exe"))) {
  $env:NODE_OPTIONS = "--use-system-ca"
  Push-Location $PSScriptRoot
  & $node "node_modules\electron\install.js"
  Pop-Location
}

Write-Host "[4/4] 组装桌面应用 ..."
$dist = Join-Path $PSScriptRoot "dist\MedChemHelper-win32-x64"
New-Item -ItemType Directory -Force -Path $dist, (Join-Path $dist "resources\app\assets") | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "node_modules\electron\dist\*") -Destination $dist -Recurse -Force
Move-Item -LiteralPath (Join-Path $dist "electron.exe") -Destination (Join-Path $dist "MedChemHelper.exe") -Force
Copy-Item -Path (Join-Path $PSScriptRoot "main.js"), (Join-Path $PSScriptRoot "package.json") -Destination (Join-Path $dist "resources\app") -Force
Copy-Item -Path (Join-Path $PSScriptRoot "assets\icon.ico") -Destination (Join-Path $dist "resources\app\assets") -Force
Copy-Item -Path (Join-Path $PSScriptRoot "dist-backend\ChemHelperBackend") -Destination (Join-Path $dist "resources\ChemHelperBackend") -Recurse -Force

$rcedit = Join-Path $PSScriptRoot "node_modules\rcedit\bin\rcedit-x64.exe"
if (Test-Path $rcedit) {
  & $rcedit (Join-Path $dist "MedChemHelper.exe") `
    --set-icon (Join-Path $PSScriptRoot "assets\icon.ico") `
    --set-version-string "ProductName" "MedChemHelper" `
    --set-version-string "FileDescription" "MedChemHelper - 化学结构速查助手桌面版" `
    --set-product-version "1.0.0" --set-file-version "1.0.0"
}

Write-Host "完成：$dist"
