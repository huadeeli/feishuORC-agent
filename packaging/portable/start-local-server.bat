@echo off
chcp 65001 >nul
setlocal
set "APP_DIR=%~dp0app"
if not exist "%APP_DIR%\orc-calc.exe" (
  echo Missing "%APP_DIR%\orc-calc.exe".
  echo Please make sure the portable package was fully extracted.
  pause
  exit /b 1
)
set "ORC_CALC_OCR_CACHE_DIR=%APP_DIR%\ocr_cache"
set "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0"
cd /d "%APP_DIR%"
"%APP_DIR%\orc-calc.exe" serve --host 127.0.0.1 --port 8765 --open
