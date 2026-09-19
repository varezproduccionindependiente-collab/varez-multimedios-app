$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "=== Varez Servicios para Multimedios - Instalacion local ===" -ForegroundColor Cyan
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
}
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
}
Write-Host "Instalacion terminada." -ForegroundColor Green
Start-Process "$PSScriptRoot\start.bat"
