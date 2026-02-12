# ClawBridge Setup (Windows PowerShell)
# =====================================
# This script launches the interactive installer wizard.
# For advanced options, run: python install.py --help

$ErrorActionPreference = "Stop"

# Find Python
$py = $null
foreach ($cmd in @("python3", "python", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $py = $found.Source
        break
    }
}

if (-not $py) {
    Write-Host "[ERROR] Python 3.10+ is required but not found." -ForegroundColor Red
    Write-Host "  Download: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Launch the installer wizard
& $py "$PSScriptRoot\install.py" @args
