@echo off
setlocal
cd /d "%~dp0\..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\installer\build_installer.ps1" %*
exit /b %ERRORLEVEL%
