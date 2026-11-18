@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "PAUSE_BUILD=1"
if /i "%~1"=="--no-pause" set "PAUSE_BUILD="
if /i "%~2"=="--no-pause" set "PAUSE_BUILD="
if /i "%~1"=="--windows-only" goto windows
if not "%~1"=="" if /i not "%~1"=="--no-pause" (
    echo Usage: build.cmd [--windows-only] [--no-pause]
    goto failed
)
python -B "%~dp0build_all.py"
if errorlevel 1 goto failed
goto success

:windows
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers"

python --version
if errorlevel 1 goto failed
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
    python -m pip install -r "..\requirements.txt"
    if errorlevel 1 goto failed
)
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    python -m pip install pyinstaller
    if errorlevel 1 goto failed
)
python -m playwright install chromium
if errorlevel 1 goto failed
python -m PyInstaller --noconfirm --workpath "%~dp0build" --distpath "%~dp0dist" "%~dp0SmallCareer.spec"
if errorlevel 1 goto failed
python -c "import ctypes, sys; from pathlib import Path; path=str(Path(sys.argv[1]).resolve()); shell=ctypes.windll.shell32; shell.SHChangeNotify.argtypes=[ctypes.c_long,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p]; shell.SHChangeNotify(0x2000,0x1005,ctypes.cast(ctypes.c_wchar_p(path),ctypes.c_void_p),None)" "%~dp0dist\SmallCareer.exe"
if errorlevel 1 goto failed
echo.
echo Ready: packing\dist\SmallCareer.exe
echo Distribute this single EXE.

:success
popd
if defined PAUSE_BUILD pause
exit /b 0

:failed
echo.
echo Build failed. See the error above.
popd
if defined PAUSE_BUILD pause
exit /b 1
