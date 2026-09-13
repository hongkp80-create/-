@echo off
cd /d "%~dp0"

python -m app.config
if errorlevel 1 goto :eof

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements-win.txt

uvicorn app.main:app --host 127.0.0.1 --port 8000
