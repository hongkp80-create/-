#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

python3 -m app.config

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements-fallback.txt

uvicorn app.main:app --host 127.0.0.1 --port 8000
