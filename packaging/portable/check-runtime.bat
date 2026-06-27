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
if not exist "%APP_DIR%\orc-calc-cli.exe" (
  echo Missing "%APP_DIR%\orc-calc-cli.exe".
  echo Please make sure the portable package was fully extracted.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\orc-calc.exe" (
  echo Missing "%APP_DIR%\orc-calc.exe". The persistent OCR service cannot start.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\ocr-runtime\python.exe" (
  echo Missing local OCR runtime.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\ocr_cache\paddlex\official_models\PP-OCRv5_mobile_det\inference.yml" (
  echo Missing PP-OCRv5 mobile detection model.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\ocr_cache\paddlex\official_models\PP-OCRv5_mobile_rec\inference.yml" (
  echo Missing PP-OCRv5 mobile recognition model.
  pause
  exit /b 1
)
if not exist "%APP_DIR%\.env" (
  call "%PACKAGE_DIR%configure-first-run.bat"
)
if not exist "%APP_DIR%\.env" (
  echo Missing app\.env. Cannot check Feishu config.
  pause
  exit /b 1
)
set "ORC_CALC_OCR_CACHE_DIR=%APP_DIR%\ocr_cache"
cd /d "%APP_DIR%"
echo.
echo ===== Feishu config check =====
"%APP_DIR%\feishu-bot.exe" --check-config
echo.
echo ===== Local OCR check =====
"%APP_DIR%\orc-calc-cli.exe" ocr-check
echo.
echo ===== Cloud OCR check =====
"%APP_DIR%\orc-calc-cli.exe" cloud-check
echo.
pause
