param([switch]$Gpu)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program $Arguments" }
}
Invoke-Checked "py" @("-3.12", "-m", "venv", ".venv")
$python = Join-Path $PWD ".venv\Scripts\python.exe"
Invoke-Checked $python @("-m", "pip", "install", "--upgrade", "pip")
if (-not $Gpu) {
    Invoke-Checked $python @("-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu")
}
Invoke-Checked $python @("-m", "pip", "install", "-e", ".[inference,dev]")
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "Install FFmpeg, add it to PATH, then reopen PowerShell. See README.md."
}
Write-Host "Setup finished. Python: $python"
