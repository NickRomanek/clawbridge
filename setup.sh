#!/usr/bin/env bash
# ClawBridge Setup (Mac / Linux)
# ===============================
# This script launches the interactive installer wizard.
# For advanced options, run: python3 install.py --help

set -e

# Find Python 3
PY=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PY="$cmd"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[ERROR] Python 3.10+ is required but not found."
    echo "  Download: https://www.python.org/downloads/"
    exit 1
fi

# Launch the installer wizard
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$PY" "$SCRIPT_DIR/install.py" "$@"
