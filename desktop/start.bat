@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
  exit /b
)
start "" ".venv\Scripts\pythonw.exe" "app.py"
