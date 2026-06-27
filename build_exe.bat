@echo off
setlocal
cd /d "%~dp0"
for %%F in (jianhui*.jpg) do if not defined ORC_JIANHUI_SAMPLE set "ORC_JIANHUI_SAMPLE=%%F"
for %%F in (jingzhou*.jpg) do if not defined ORC_JINGZHOU_SAMPLE set "ORC_JINGZHOU_SAMPLE=%%F"
if not exist ".venv-build\Scripts\python.exe" (
  python -m venv .venv-build
)
".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
".venv-build\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onedir --windowed --name orc-calc ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "%ORC_JIANHUI_SAMPLE%;." ^
  --add-data "%ORC_JINGZHOU_SAMPLE%;." ^
  orc-calc.py
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --onedir --windowed --name orc-calc-cli ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "%ORC_JIANHUI_SAMPLE%;." ^
  --add-data "%ORC_JINGZHOU_SAMPLE%;." ^
  orc-calc-cli.py
copy /Y "dist\orc-calc-cli\orc-calc-cli.exe" "dist\orc-calc\orc-calc-cli.exe" >nul
copy /Y "%ORC_JIANHUI_SAMPLE%" "dist\orc-calc\%ORC_JIANHUI_SAMPLE%" >nul
copy /Y "%ORC_JINGZHOU_SAMPLE%" "dist\orc-calc\%ORC_JINGZHOU_SAMPLE%" >nul
echo.
echo Build finished. Portable folder: dist\orc-calc
