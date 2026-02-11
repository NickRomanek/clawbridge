#!/usr/bin/env bash
# ClawBridge Setup Script (Mac / Linux)
# Usage: chmod +x setup.sh && ./setup.sh

set -e

echo "=============================="
echo " ClawBridge Setup"
echo "=============================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3.11+ is required but not found."
    echo "  Install: https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "[OK] Python $PY_VERSION found"

# Check Node (for OpenClaw)
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo "[OK] Node $NODE_VERSION found (OpenClaw engine available)"
else
    echo "[WARN] Node.js not found. OpenClaw engine will not be available."
    echo "  Install Node 22+: https://nodejs.org/"
    echo "  Continuing with browser-use engine only..."
fi

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
echo "Installing Chromium browser..."
playwright install chromium

# Install OpenClaw if Node is available
if command -v node &> /dev/null; then
    echo "Installing OpenClaw..."
    npm install -g openclaw@latest 2>/dev/null || echo "[WARN] OpenClaw install failed. You can install it manually later."
fi

# Setup .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "[ACTION REQUIRED] Edit .env and add your API key(s):"
    echo "  nano .env"
fi

echo ""
echo "=============================="
echo " Setup complete!"
echo "=============================="
echo ""
echo "To start ClawBridge:"
echo "  source .venv/bin/activate"
echo "  python -m clawbridge"
echo ""
echo "Then open: http://localhost:8765"
echo ""
