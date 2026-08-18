@echo off
rem 把本地源码推送到 GitHub（远程地址已配置为 MedChemHelper）
setlocal
cd /d "%~dp0"

if not "%~1"=="" (
  echo 设置远程仓库为 %~1
  git remote remove origin >nul 2>nul
  git remote add origin %~1
)

git remote -v
git branch -M main
git push -u origin main

echo.
echo 推送结束。如果提示需要登录，请按提示在浏览器/终端中完成 GitHub 认证。
pause
