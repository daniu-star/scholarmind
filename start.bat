@echo off
REM ============================================================
REM  ScholarMind Startup Script
REM  Starts FastAPI backend and opens browser (same-origin access)
REM ============================================================

REM Use UTF-8 code page so backend logs (Chinese) render correctly
chcp 65001 >nul

REM Switch to script directory (project root)
cd /d "%~dp0"

echo.
echo ============================================================
echo  ScholarMind Startup
echo ============================================================

REM Step 1: Check Python
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    echo         Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo [INFO] %PY_VER%

REM Step 2: Activate virtual environment if exists (avoid parentheses in values)
echo.
echo [2/5] Checking virtual environment...
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    call ".venv\Scripts\activate.bat"
    echo [INFO] Activated .venv at project root
    goto :venv_done
)
if exist "src\backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=src\backend\.venv\Scripts\python.exe"
    call "src\backend\.venv\Scripts\activate.bat"
    echo [INFO] Activated src\backend\.venv
    goto :venv_done
)
echo [INFO] No .venv found, using system Python
:venv_done

REM Step 3: Check critical dependencies (fastapi/uvicorn)
echo.
echo [3/5] Checking dependencies...
%PYTHON_EXE% -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] fastapi/uvicorn not installed in current Python environment.
    echo [ERROR] Please run: pip install -r src\backend\requirements.txt
    echo.
    pause
    exit /b 1
)
echo [INFO] fastapi/uvicorn OK
%PYTHON_EXE% -c "import langgraph" >nul 2>&1
if errorlevel 1 (
    echo [WARN] langgraph not installed. Pipeline feature may be unavailable.
    echo [WARN] Run: pip install langgraph
) else (
    echo [INFO] langgraph installed
)

REM Step 4: Kill any process on port 8000 (avoid port conflict)
echo.
echo [4/5] Preparing port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [INFO] Killing existing process on port 8000: PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

REM Step 5: Launch browser-opener (async PS1), then run uvicorn in foreground
echo.
echo [5/5] Starting backend...

echo [INFO] Launching browser-opener (polls /api/v1/health, opens browser when ready)...
start /b powershell -ExecutionPolicy Bypass -File "%~dp0wait_and_open.ps1"

echo.
echo ============================================================
echo  ScholarMind Backend Starting
echo ------------------------------------------------------------
echo  Backend:  http://localhost:8000
echo  Frontend: http://localhost:8000/app/interactive-prototype.html
echo ------------------------------------------------------------
echo  Keep this window open while using ScholarMind.
echo  To stop: press Ctrl+C or close this window.
echo ============================================================
echo.
echo Backend logs:
echo.
echo NOTE: Backend starts in ~5 seconds. ML models load in background.
echo       Browser will open automatically when ready.
echo.

REM P0 Task 5.8: Use factory mode (create_app) as app.py has no module-level 'app'.
REM Enable rate limiting for local production-like default.
set "RATE_LIMIT_ENABLED=true"
REM Use HuggingFace mirror to avoid model download timeouts in mainland China
set "HF_ENDPOINT=https://hf-mirror.com"
REM P0 Task 1.7/2.7: Security kill-switches (defaults: both OFF).
REM Bind to 127.0.0.1 only: avoid exposing backend to LAN/WAN by default.
%PYTHON_EXE% -m uvicorn src.backend.app:create_app --factory --host 127.0.0.1 --port 8000

echo.
echo Backend stopped. Press any key to close...
pause >nul
