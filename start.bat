@echo off
setlocal
cd /d "%~dp0"

set "VenvPy=.venv\Scripts\python.exe"

if not exist "%VenvPy%" (
  echo [Setup] First run: creating isolated Python environment...
  where python >nul 2>nul
  if errorlevel 1 (
    echo [Error] Python not found. Please install Python 3.10+ first.
    pause
    exit /b 1
  )
  python -m venv .venv || (echo [Error] Failed to create venv. & pause & exit /b 1)
)

"%VenvPy%" -c "import rdkit" >nul 2>nul
if errorlevel 1 (
  echo [Setup] Installing RDKit into .venv (about 1 minute on first run)...
  "%VenvPy%" -m pip install --upgrade pip --quiet --disable-pip-version-check
  "%VenvPy%" -m pip install "numpy<2" rdkit-pypi --quiet --disable-pip-version-check
)

echo [Start] Launching Chem Helper at http://127.0.0.1:8765/
"%VenvPy%" server.py %*
if errorlevel 1 (
  echo [Fallback] Trying system Python...
  python server.py %*
)
pause
