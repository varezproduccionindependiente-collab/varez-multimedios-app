@echo off
chcp 65001 >nul
title Gestor de Informes FM Ciudad
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Es la primera vez que se ejecuta.
  call INSTALAR_PRIMERA_VEZ.bat
)

if not exist ".venv\Scripts\python.exe" exit /b 1

call ".venv\Scripts\activate.bat"
python server.py
pause
