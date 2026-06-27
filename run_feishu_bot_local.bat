@echo off
setlocal
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%~dp0"
set ORC_OCR_MODE=local
call run_feishu_bot.bat
