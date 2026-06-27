@echo off
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "ORC_CALC_OCR_CACHE_DIR=%%~fI\orc_calc_ocr_cache"
for %%F in (jianhui*.jpg) do if not defined ORC_JIANHUI_SAMPLE set "ORC_JIANHUI_SAMPLE=%%F"
for %%F in (jingzhou*.jpg) do if not defined ORC_JINGZHOU_SAMPLE set "ORC_JINGZHOU_SAMPLE=%%F"
set "HOME=%ORC_CALC_OCR_CACHE_DIR%\home"
set "USERPROFILE=%ORC_CALC_OCR_CACHE_DIR%\home"
set "PADDLE_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddle"
set "PADDLEOCR_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddleocr"
set "PADDLE_PDX_CACHE_HOME=%ORC_CALC_OCR_CACHE_DIR%\paddlex"
set "XDG_CACHE_HOME=%ORC_CALC_OCR_CACHE_DIR%\xdg"
if not exist ".venv-ocr\Scripts\python.exe" (
  call install_ocr_cpu.bat
)
".venv-ocr\Scripts\python.exe" -m pip install -r requirements-build.txt
".venv-ocr\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onedir --windowed --name orc-calc ^
  --exclude-module paddleocr ^
  --exclude-module paddlex ^
  --exclude-module paddle ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "%ORC_JIANHUI_SAMPLE%;." ^
  --add-data "%ORC_JINGZHOU_SAMPLE%;." ^
  orc-calc.py
".venv-ocr\Scripts\python.exe" -m PyInstaller --noconfirm --onedir --console --name orc-calc-cli ^
  --exclude-module paddleocr ^
  --exclude-module paddlex ^
  --exclude-module paddle ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "%ORC_JIANHUI_SAMPLE%;." ^
  --add-data "%ORC_JINGZHOU_SAMPLE%;." ^
  orc-calc-cli.py
copy /Y "dist\orc-calc-cli\orc-calc-cli.exe" "dist\orc-calc\orc-calc-cli.exe" >nul
copy /Y "%ORC_JIANHUI_SAMPLE%" "dist\orc-calc\%ORC_JIANHUI_SAMPLE%" >nul
copy /Y "%ORC_JINGZHOU_SAMPLE%" "dist\orc-calc\%ORC_JINGZHOU_SAMPLE%" >nul
echo.
echo OCR build finished. Portable folder: dist\orc-calc
