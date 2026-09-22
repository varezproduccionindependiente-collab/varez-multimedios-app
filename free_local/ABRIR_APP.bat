@echo off
chcp 65001 >nul
title Gestor de Informes FM Ciudad
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Es la primera vez que se ejecuta.
  call INSTALAR_PRIMERA_VEZ.bat
)

if not exist ".venv\Scripts\python.exe" exit /b 1

where ollama >nul 2>&1
if not errorlevel 1 (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 1 ^| Out-Null } catch { Start-Process -WindowStyle Hidden ollama -ArgumentList 'serve'; Start-Sleep -Seconds 2 }"
)

call ".venv\Scripts\activate.bat"
python server.py
pause
