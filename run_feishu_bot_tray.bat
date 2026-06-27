@echo off
setlocal
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%~dp0"
if exist ".venv-feishu\Scripts\pythonw.exe" (
  start "" ".venv-feishu\Scripts\pythonw.exe" -m feishu_bot.tray_app
) else if exist ".venv-feishu\Scripts\python.exe" (
  start "" ".venv-feishu\Scripts\python.exe" -m feishu_bot.tray_app
) else (
  start "" pythonw -m feishu_bot.tray_app
)
