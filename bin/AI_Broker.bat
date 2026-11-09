@echo off
set "PYTHONPATH=%~dp0.."
start "" "%~dp0..\.venv\Scripts\pythonw.exe" -m aibroker.gui
