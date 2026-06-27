@echo off
setlocal
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%~dp0"
python orc-calc.py
