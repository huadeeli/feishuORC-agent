@echo off
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
if exist "..\app\ocr-runtime\python-console.exe" (
  set PY=..\app\ocr-runtime\python-console.exe
) else if exist ".venv-feishu\Scripts\python.exe" (
  set PY=.venv-feishu\Scripts\python.exe
) else (
  set PY=python
)
"%PY%" -m unittest tests.test_core tests.test_feishu_bot tests.test_feishu_cards tests.test_feishu_tray tests.test_agent_boundaries tests.test_project_protection
