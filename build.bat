@echo off
REM =========================================================
REM  Smart Text Extractor — Build Script
REM  Run from the project root: build.bat
REM =========================================================

echo [TextEx Build] Activating virtual environment...
call .\venv\Scripts\activate.bat

echo [TextEx Build] Running PyInstaller...
.\venv\Scripts\python.exe -m PyInstaller TextEx.spec --noconfirm --clean

echo.
echo [TextEx Build] Done. Output is in the dist\ folder.
pause
