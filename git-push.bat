@echo off
rem MedChemHelper: auto commit + confirm push
setlocal
cd /d "%~dp0"

echo ============================================
echo   MedChemHelper - Commit & Push
echo ============================================
echo.

rem 1) stage all changes
git add -A

rem 2) check if there is anything to commit
git diff --cached --quiet
if errorlevel 1 goto has_changes

echo [Info] No changes detected, nothing to commit.
goto ask

:has_changes
echo The following files will be committed:
git diff --cached --name-status
echo.
git commit -m "MedChemHelper"
if errorlevel 1 (
  echo.
  echo [Error] Commit failed. Please check Git configuration.
  pause
  exit /b 1
)
echo.
echo [Done] Committed. Summary of this commit:
git show --stat --oneline HEAD
echo.

:ask
set /p CONFIRM=Push to GitHub now? (Y/N):
if /i "%CONFIRM%"=="Y" goto do_push
if /i "%CONFIRM%"=="N" (
  echo.
  echo Pushing cancelled. Changes are saved locally.
  echo Press any key to exit...
  pause >nul
  exit /b 0
)
echo Please enter Y or N.
goto ask

:do_push
echo.
echo Pushing to GitHub ...
git push origin main
if errorlevel 1 (
  echo.
  echo [Error] Push failed. Please check network or login status.
  echo Press any key to exit...
  pause >nul
  exit /b 1
)
echo.
echo [Done] Pushed to GitHub successfully.
echo Press any key to exit...
pause >nul
exit /b 0
