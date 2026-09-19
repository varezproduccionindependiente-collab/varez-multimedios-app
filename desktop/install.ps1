$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "=== Varez Servicios para Multimedios - Instalacion local ===" -ForegroundColor Cyan
$VarezRoot = "D:\VarezMultimedios"
$ModelsRoot = Join-Path $VarezRoot "models"
$OllamaModels = Join-Path $ModelsRoot "ollama"
$HFHome = Join-Path $ModelsRoot "huggingface"
New-Item -ItemType Directory -Force -Path $OllamaModels | Out-Null
New-Item -ItemType Directory -Force -Path $HFHome | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $VarezRoot "outputs") | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $OllamaModels, "User")
[Environment]::SetEnvironmentVariable("HF_HOME", $HFHome, "User")
[Environment]::SetEnvironmentVariable("HUGGINGFACE_HUB_CACHE", (Join-Path $HFHome "hub"), "User")
$env:OLLAMA_MODELS = $OllamaModels
$env:HF_HOME = $HFHome
$env:HUGGINGFACE_HUB_CACHE = Join-Path $HFHome "hub"
Write-Host "Modelos y resultados: $VarezRoot" -ForegroundColor Green
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
