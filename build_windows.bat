@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo KorNet Windows build
echo ========================================

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python launcher "py" was not found.
    echo Install Python 3.10+ and enable the Python launcher.
    exit /b 1
)

py -3 -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10 or newer is required'"
if errorlevel 1 (
    echo ERROR: Python 3.10+ is required.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 exit /b 1

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

if exist "build\KorNet" rmdir /s /q "build\KorNet"
python -m PyInstaller --noconfirm --clean KorNet.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. Existing dist output has not been manually deleted.
    exit /b 1
)

if exist "dist\KorNet.exe" (
    echo SUCCESS: dist\KorNet.exe
) else (
    echo ERROR: Build completed but dist\KorNet.exe was not found.
    exit /b 1
)
endlocal
