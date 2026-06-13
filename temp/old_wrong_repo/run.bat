@echo off
setlocal EnableDelayedExpansion

echo =======================================================
echo   AXIOM — Customer Intelligence Agent System Launcher
echo =======================================================
echo.

:: Check for Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

:: Resolve virtual environment
set VENV_DIR=.axiom_env
if exist "%VENV_DIR%\Scripts\python.exe" (
    set PYTHON="%VENV_DIR%\Scripts\python.exe"
    set PIP="%VENV_DIR%\Scripts\pip.exe"
    echo [INFO] Using virtual environment: %VENV_DIR%
) else (
    echo [WARN] Virtual environment not found at %VENV_DIR%.
    echo [INFO] Creating virtual environment...
    python -m venv %VENV_DIR%
    set PYTHON="%VENV_DIR%\Scripts\python.exe"
    set PIP="%VENV_DIR%\Scripts\pip.exe"
    echo [INFO] Installing dependencies...
    %PIP% install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check requirements.txt and your network.
        pause
        exit /b 1
    )
)

:: Load .env if it exists
if exist .env (
    echo [INFO] Loading environment from .env
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" if not "!line!"=="" (
            set "%%A=%%B"
        )
    )
) else (
    echo [WARN] .env not found. Copy .env.example to .env and fill in API keys.
)

:: Port configuration
if not defined PORT_GATEWAY  set PORT_GATEWAY=8080
if not defined PORT_PERSONAL set PORT_PERSONAL=8081
if not defined PORT_CS       set PORT_CS=8082
if not defined PORT_RESEARCH set PORT_RESEARCH=8083

echo.
echo [1/5] Starting Personal Agent   on port %PORT_PERSONAL%...
start "Axiom-Personal"   cmd /k %PYTHON% -m uvicorn apps.app_personal:app --host 0.0.0.0 --port %PORT_PERSONAL%

echo [2/5] Starting CS Agent         on port %PORT_CS%...
start "Axiom-CS"         cmd /k %PYTHON% -m uvicorn apps.app_cs:app       --host 0.0.0.0 --port %PORT_CS%

echo [3/5] Starting Research Agent   on port %PORT_RESEARCH%...
start "Axiom-Research"   cmd /k %PYTHON% -m uvicorn apps.app_research:app  --host 0.0.0.0 --port %PORT_RESEARCH%

:: Give the workers 4 seconds to bind their ports before the gateway starts
echo [4/5] Waiting for workers to bind...
timeout /t 4 /nobreak >nul

echo [5/5] Starting Phalanx Gateway  on port %PORT_GATEWAY%...
start "Axiom-Gateway"    cmd /k %PYTHON% -m uvicorn gateway.main:app       --host 0.0.0.0 --port %PORT_GATEWAY%

echo.
echo -------------------------------------------------------
echo   All services started. Check each terminal window.
echo.
echo   Gateway:  http://localhost:%PORT_GATEWAY%
echo   Personal: http://localhost:%PORT_PERSONAL%
echo   CS:       http://localhost:%PORT_CS%
echo   Research: http://localhost:%PORT_RESEARCH%
echo.
echo   AgentCard: http://localhost:%PORT_GATEWAY%/.well-known/agent-card.json
echo   SSE:       http://localhost:%PORT_GATEWAY%/sse/{session_id}
echo -------------------------------------------------------
echo.
pause