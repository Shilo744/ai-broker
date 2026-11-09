@echo off
rem AI Broker: double-click to start. The first time (or when something is missing) it also installs what it needs into a private .venv folder here.
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"

rem 1) everything already installed? start at once, with no console window.
if exist "%VPY%" (
    "%VPY%" -c "import PySide6, psutil, mcp, pydantic" >nul 2>nul
    if not errorlevel 1 goto start
)

echo.
echo  AI Broker: first start, installing what it needs (a few minutes, needs internet).
echo.

rem 2) find Python 3.10+ (the py launcher first, then python on PATH)
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo  Python 3.10 or newer was not found.
    echo  Install it from https://www.python.org/downloads/windows/  ^(tick "Add python.exe to PATH"^), then double-click this file again.
    echo.
    pause
    exit /b 1
)

rem 3) private environment + packages
if not exist "%VPY%" (
    echo  Creating the private environment...
    %PY% -m venv "%~dp0.venv"
    if errorlevel 1 goto failed
)
echo  Installing packages...
"%VPY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
echo.
echo  Done.

:start
start "" "%~dp0.venv\Scripts\pythonw.exe" -m aibroker.gui
exit /b 0

:failed
echo.
echo  The installation failed. Check the internet connection and try again; the messages above say what went wrong.
echo.
pause
exit /b 1
