@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package_portable_zip.ps1"
exit /b %ERRORLEVEL%
