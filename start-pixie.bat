@echo off
setlocal
cd /d "%~dp0"
title Pixie
echo.
echo  ===  Pixie  ===
echo  The first run installs everything (can take 10-20 min). Later runs start in seconds.
echo.

REM ---------- 1. Python ----------
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if defined PY goto have_python
echo [1/5] Installing Python 3.12...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" (
  echo Could not install Python automatically. Install it from https://python.org and run this file again.
  pause & exit /b 1
)
:have_python
echo [1/5] Python OK

REM ---------- 2. Python packages (only when requirements.txt changed) ----------
if not exist ".venv\Scripts\python.exe" (
  echo [2/5] Creating virtual environment...
  %PY% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"
for /f "usebackq delims=" %%h in (`"%VPY%" -c "import hashlib;print(hashlib.sha1(open('requirements.txt','rb').read()).hexdigest())"`) do set "REQ_HASH=%%h"
set "OLD_HASH="
if exist ".venv\requirements.sha" set /p OLD_HASH=<".venv\requirements.sha"
if "%REQ_HASH%"=="%OLD_HASH%" goto packages_ok
echo [2/5] Installing Python packages...
"%VPY%" -m pip install -q --upgrade pip
"%VPY%" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Package install failed - see the error above.
  pause & exit /b 1
)
>".venv\requirements.sha" echo %REQ_HASH%
:packages_ok
if not exist "config.yaml" copy /y "config.example.yaml" "config.yaml" >nul
echo [2/5] Packages OK

REM ---------- 3. Ollama ----------
set "OLLAMA=ollama"
where ollama >nul 2>nul && goto have_ollama
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  goto have_ollama
)
echo [3/5] Installing Ollama...
winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" (
  echo Could not install Ollama automatically. Install it from https://ollama.com and run this file again.
  pause & exit /b 1
)
:have_ollama
"%OLLAMA%" list >nul 2>nul
if errorlevel 1 (
  start "" /min "%OLLAMA%" serve
  timeout /t 5 /nobreak >nul
)
echo [3/5] Ollama OK

REM ---------- 4. AI model (the one in config.yaml) ----------
set "MODEL=qwen2.5:7b"
for /f "usebackq delims=" %%m in (`"%VPY%" -c "from pixie.config import CONFIG;print(CONFIG['ollama']['model'])"`) do set "MODEL=%%m"
"%OLLAMA%" list | findstr /i /c:"%MODEL%" >nul
if errorlevel 1 (
  echo [4/5] Downloading the AI model %MODEL% ^(several GB, first time only^)...
  "%OLLAMA%" pull %MODEL%
)
echo [4/5] AI model %MODEL% OK

REM ---------- 5. Start Pixie ----------
echo [5/5] Starting Pixie...
start "" ".venv\Scripts\pythonw.exe" -m pixie
echo.
echo  Pixie is running in your system tray.
echo  Hold RIGHT ALT to talk, double-tap it to type.
echo  (The first voice command downloads the speech model.)
echo  Problems? Check pixie.log in this folder.
echo.
timeout /t 6
