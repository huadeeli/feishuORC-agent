@echo off
chcp 65001 >nul
setlocal
set "LAUNCHER=%~dp0start-local-tray.vbs"
if not exist "%LAUNCHER%" (
  echo Missing "%LAUNCHER%".
  pause
  exit /b 1
)
wscript.exe "%LAUNCHER%"
exit /b 0
