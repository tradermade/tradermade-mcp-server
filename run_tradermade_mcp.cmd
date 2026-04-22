@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "BOOTSTRAP=%SCRIPT_DIR%run_tradermade_mcp.py"
set "VENV_PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
  "%VENV_PYTHON%" "%BOOTSTRAP%" %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%BOOTSTRAP%" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%BOOTSTRAP%" %*
  exit /b %ERRORLEVEL%
)

echo [tradermade-bootstrap] Could not find Python 3.10+ on PATH. 1>&2
exit /b 1
