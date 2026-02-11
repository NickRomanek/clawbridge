# ClawBridge Setup Script (Windows PowerShell)
# Usage: .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host "==============================" -ForegroundColor Cyan
Write-Host " ClawBridge Setup" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "[OK] $pyVersion found" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python 3.11+ is required but not found." -ForegroundColor Red
    Write-Host "  Install: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check Node (for OpenClaw)
try {
    $nodeVersion = node --version 2>&1
    Write-Host "[OK] Node $nodeVersion found (OpenClaw engine available)" -ForegroundColor Green
    $hasNode = $true
} catch {
    Write-Host "[WARN] Node.js not found. OpenClaw engine will not be available." -ForegroundColor Yellow
    Write-Host "  Install Node 22+: https://nodejs.org/" -ForegroundColor Yellow
    Write-Host "  Continuing with browser-use engine only..." -ForegroundColor Yellow
    $hasNode = $false
}

# Create virtual environment
Write-Host ""
Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
python -m venv .venv
& .\.venv\Scripts\Activate.ps1

# Install Python dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
Write-Host "Installing Chromium browser..." -ForegroundColor Cyan
playwright install chromium

# Install OpenClaw if Node is available
if ($hasNode) {
    Write-Host "Installing OpenClaw..." -ForegroundColor Cyan
    try {
        npm install -g openclaw@latest 2>$null
    } catch {
        Write-Host "[WARN] OpenClaw install failed. You can install it manually later." -ForegroundColor Yellow
    }
}

# Setup .env if not exists
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host ""
    Write-Host "[ACTION REQUIRED] Edit .env and add your API key(s):" -ForegroundColor Yellow
    Write-Host "  notepad .env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==============================" -ForegroundColor Cyan
Write-Host " Setup complete!" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To start ClawBridge:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python -m clawbridge" -ForegroundColor White
Write-Host ""
Write-Host "Then open: http://localhost:8765" -ForegroundColor Green
Write-Host ""
