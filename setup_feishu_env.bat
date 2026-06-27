@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-feishu\Scripts\python.exe" (
  python -m venv .venv-feishu
)
".venv-feishu\Scripts\python.exe" -m pip install --upgrade pip
".venv-feishu\Scripts\python.exe" -m pip install -r requirements-feishu.txt
".venv-feishu\Scripts\python.exe" -m feishu_bot.main --check-config
