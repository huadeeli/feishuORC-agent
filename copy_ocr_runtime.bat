@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-ocr\Scripts\python.exe" (
  call install_ocr_cpu.bat
)
if not exist "dist\orc-calc\orc-calc.exe" (
  call build_exe_ocr.bat
)
robocopy ".venv-ocr" "dist\orc-calc\.venv-ocr" /E /XD "__pycache__" /XF "*.pyc" "*.pyo"
set "RC=%ERRORLEVEL%"
if %RC% LEQ 7 exit /b 0
exit /b %RC%
