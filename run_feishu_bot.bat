@echo off
setlocal
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%~dp0"
if exist ".venv-feishu\Scripts\python.exe" (
  ".venv-feishu\Scripts\python.exe" -m feishu_bot.main
) else (
  python -m feishu_bot.main
)
