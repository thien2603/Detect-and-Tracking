param([switch]$Download, [switch]$Api)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run scripts\setup.ps1 first." }
if ($Download) {
    & $python -m scripts.download_model
    if ($LASTEXITCODE -ne 0) { throw "Model download failed" }
    & $python -m scripts.download_expressway
    if ($LASTEXITCODE -ne 0) { throw "Video download failed" }
}
if ($Api) {
    $env:CONFIG_PATH = "configs/vietnam-expressway.yaml"
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
} else {
    & $python -m scripts.render_video --config configs/vietnam-expressway.yaml
}
if ($LASTEXITCODE -ne 0) { throw "Run failed" }
