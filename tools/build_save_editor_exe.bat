@echo off
setlocal
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\build_save_editor_exe.ps1" %*
exit /b %ERRORLEVEL%
