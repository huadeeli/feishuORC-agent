@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-build\Scripts\python.exe" (
  python -m venv .venv-build
)
".venv-build\Scripts\python.exe" -m pip install --upgrade pip
".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
".venv-build\Scripts\python.exe" -m pip install -r requirements-feishu.txt
".venv-build\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onedir --console --name feishu-bot ^
  --exclude-module paddleocr ^
  --exclude-module paddlex ^
  --exclude-module paddle ^
  feishu-bot.py
".venv-build\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onedir --windowed --name feishu-bot-tray ^
  --exclude-module paddleocr ^
  --exclude-module paddlex ^
  --exclude-module paddle ^
  feishu-bot-tray.py
echo.
echo Feishu build finished. Portable folders: dist\feishu-bot and dist\feishu-bot-tray
