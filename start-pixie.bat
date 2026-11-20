@echo off
setlocal
cd /d "%~dp0"
title Pixie setup
echo.
echo  ===  Pixie setup  ===
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

REM ---------- 2. Ollama ----------
set "OLLAMA=ollama"
where ollama >nul 2>nul && goto have_ollama
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  goto have_ollama
)
echo [2/5] Installing Ollama...
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
echo [2/5] Ollama OK

REM ---------- 3. AI model ----------
"%OLLAMA%" list | findstr /i "qwen2.5:7b" >nul
if errorlevel 1 (
  echo [3/5] Downloading the AI model qwen2.5:7b ^(about 4.7 GB^)...
  "%OLLAMA%" pull qwen2.5:7b
)
echo [3/5] AI model OK

REM ---------- 4. Python packages ----------
if not exist ".venv\Scripts\python.exe" (
  echo [4/5] Creating virtual environment...
  %PY% -m venv .venv
)
echo [4/5] Installing / checking Python packages...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Package install failed - see the error above.
  pause & exit /b 1
)
if not exist "config.yaml" copy /y "config.example.yaml" "config.yaml" >nul
echo [4/5] Packages OK

REM ---------- 5. Start Pixie ----------
echo [5/5] Starting Pixie...
start "" ".venv\Scripts\pythonw.exe" -m pixie
echo.
echo  Pixie is running in your system tray.
echo  Hold RIGHT ALT to talk, double-tap it to type.
echo  (The first voice command downloads the speech model, ~500 MB.)
echo  Problems? Check pixie.log in this folder.
echo.
timeout /t 8
