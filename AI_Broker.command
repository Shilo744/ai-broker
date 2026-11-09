#!/bin/bash
# AI Broker for macOS and Linux: double-click (macOS) or run in a terminal. The first time (or when something is missing) it also installs what it needs
# into a private .venv folder here. If macOS refuses to open it, right-click > Open once, or run:  bash AI_Broker.command
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
VPY="$HERE/.venv/bin/python"
export PYTHONPATH="$HERE"

# 1) everything already installed? start at once.
if [ -x "$VPY" ] && "$VPY" -c "import PySide6, psutil, mcp, pydantic" >/dev/null 2>&1; then
    nohup "$VPY" -m aibroker.gui >/dev/null 2>&1 &
    exit 0
fi

echo
echo " AI Broker: first start, installing what it needs (a few minutes, needs internet)."
echo

# 2) find Python 3.10 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >/dev/null 2>&1; then
        PY="$c"
        break
    fi
done
if [ -z "$PY" ]; then
    echo " Python 3.10 or newer was not found."
    echo " Install it from https://www.python.org/downloads/ (or with Homebrew:  brew install python@3.12 ), then run this file again."
    echo
    read -r -p " Press Enter to close. " _
    exit 1
fi

# 3) private environment + packages
if [ ! -x "$VPY" ]; then
    echo " Creating the private environment..."
    "$PY" -m venv "$HERE/.venv" || { echo " Could not create the environment."; read -r -p " Press Enter to close. " _; exit 1; }
fi
echo " Installing packages..."
if ! "$VPY" -m pip install --disable-pip-version-check -r "$HERE/requirements.txt"; then
    echo
    echo " The installation failed. Check the internet connection and try again; the messages above say what went wrong."
    read -r -p " Press Enter to close. " _
    exit 1
fi
echo
echo " Done."
nohup "$VPY" -m aibroker.gui >/dev/null 2>&1 &
exit 0
