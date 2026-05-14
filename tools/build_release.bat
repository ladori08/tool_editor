@echo off
setlocal
cd /d "%~dp0\.."

echo [INFO] Building EXE...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\build_save_editor_exe.ps1" -SkipDependencyInstall
if errorlevel 1 (
  echo [ERROR] EXE build failed.
  exit /b 1
)

echo [INFO] Building Setup (Inno)...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\installer\build_installer.ps1" -SkipExeBuild
if errorlevel 1 (
  echo [ERROR] Setup build failed.
  exit /b 1
)

echo [DONE] Release build completed.
echo EXE   : tools\PokemonIndigoSaveEditor.exe
echo Setup : tools\installer\dist\PokemonSaveEditor_Setup.exe
exit /b 0
