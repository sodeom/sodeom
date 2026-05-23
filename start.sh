#!/bin/bash
set -eu
export PYTHONUNBUFFERED=true

VENV=".venv"
[ ! -d "$VENV" ] && python3 -m venv "$VENV"

if [ -f "requirements.txt" ]; then
  "$VENV/bin/pip" install -q -r requirements.txt
fi

"$VENV/bin/python" app.py
