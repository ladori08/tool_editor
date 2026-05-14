@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

if exist "tools\dist\PokemonIndigoSaveEditor.exe" (
    start "" "tools\dist\PokemonIndigoSaveEditor.exe"
    exit /b 0
)

if exist "tools\PokemonIndigoSaveEditor.exe" (
    start "" "tools\PokemonIndigoSaveEditor.exe"
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found in PATH and no built EXE was found.
    echo.
    echo Fix option A (recommended): run the packaged EXE:
    echo   tools\PokemonIndigoSaveEditor.exe
    echo.
    echo Fix option B: install Python and add to PATH, then run this launcher again.
    echo.
    pause
    exit /b 1
)

echo [INFO] Running startup checks...
python -X utf8 -c "import py_compile; py_compile.compile(r'tools\pokemon_indigo_save_editor_gui.py', doraise=True)"
if errorlevel 1 (
    echo.
    echo [ERROR] Startup check failed. See traceback above.
    echo Batch window will stay open for logs.
    echo.
    pause
    exit /b 1
)

python -X utf8 -c "import pathlib,sys; sys.path.insert(0, str((pathlib.Path.cwd()/'tools').resolve())); import pokemon_indigo_save_editor_gui" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Cannot import the GUI module.
    echo Run directly with: python tools\pokemon_indigo_save_editor_gui.py
    echo Batch window will stay open for logs.
    echo.
    python tools\pokemon_indigo_save_editor_gui.py
    echo.
    pause
    exit /b 1
)

start "" pythonw tools\pokemon_indigo_save_editor_gui.py
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start GUI process.
    echo Batch window will stay open for logs.
    echo.
    pause
    exit /b 1
)

exit /b 0
