@echo off
chcp 65001 >nul
setlocal
set "PACKAGE_DIR=%~dp0"
set "APP_DIR=%PACKAGE_DIR%app"
if not exist "%APP_DIR%\feishu-bot.exe" (
  echo Missing "%APP_DIR%\feishu-bot.exe".
  echo Please make sure the portable package was fully extracted.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\.env" (
  call "%PACKAGE_DIR%configure-first-run.bat"
)
if not exist "%APP_DIR%\.env" (
  echo Missing app\.env. Cannot start Feishu bot.
  pause
  exit /b 1
)
set "ORC_CALC_OCR_CACHE_DIR=%APP_DIR%\ocr_cache"
cd /d "%APP_DIR%"
"%APP_DIR%\feishu-bot.exe"
if errorlevel 1 pause
