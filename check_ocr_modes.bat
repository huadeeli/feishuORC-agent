@echo off
setlocal
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%~dp0"
if exist ".venv-feishu\Scripts\python.exe" (
  set PY=.venv-feishu\Scripts\python.exe
) else (
  set PY=python
)
"%PY%" orc-calc.py ocr-check
"%PY%" orc-calc.py cloud-check
