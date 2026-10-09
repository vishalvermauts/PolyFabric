# Windows PowerShell Installation Script for Infinite Memory Protocol
$ErrorActionPreference = "Stop"

Write-Host "=== Installing Infinite Memory Protocol (IMP) ===" -ForegroundColor Cyan

# Test Python
try {
    $pythonVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Write-Host "Detected Python version: $pythonVer" -ForegroundColor Green
} catch {
    Write-Error "Python is not detected on PATH. Please install Python 3.10+."
    exit 1
}

Write-Host "Upgrading pip and installing package in editable mode..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -e .

Write-Host "=== Infinite Memory Protocol successfully installed! ===" -ForegroundColor Green
Write-Host "Try running: memory-mesh --help" -ForegroundColor Yellow
