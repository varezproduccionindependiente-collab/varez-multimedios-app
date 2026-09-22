@echo off
chcp 65001 >nul
title Gestor de Informes FM Ciudad - Instalacion gratis
cd /d "%~dp0"

echo.
echo ================================================
echo   GESTOR DE INFORMES FM CIUDAD - MODO GRATIS
echo ================================================
echo.

where py >nul 2>&1
if errorlevel 1 (
  where python >nul 2>&1
  if errorlevel 1 (
    echo No encuentro Python en esta PC.
    echo Instala Python 3.11 o 3.12 y marca "Add Python to PATH".
    echo.
    pause
    exit /b 1
  )
  set PY=python
) else (
  set PY=py
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Preparando el entorno local...
  %PY% -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"

echo [2/3] Instalando componentes gratuitos...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Revisando Ollama...
where ollama >nul 2>&1
if errorlevel 1 (
  echo.
  echo Ollama no esta instalado. La app igual funciona con resumen de respaldo.
  echo Para mejores titulos y resumenes, instala Ollama gratis y despues ejecuta:
  echo   ollama pull qwen2.5:3b
  echo.
) else (
  echo Ollama encontrado.
  ollama list | findstr /I /C:"qwen2.5:3b" >nul 2>&1
  if errorlevel 1 (
    echo Descargando el modelo gratuito qwen2.5:3b...
    ollama pull qwen2.5:3b
  )
)

echo.
echo Instalacion terminada.
echo A partir de ahora usa ABRIR_APP.bat
echo.
pause
exit /b 0

:error
echo.
echo Ocurrio un error durante la instalacion.
pause
exit /b 1
