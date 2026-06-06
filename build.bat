@echo off
setlocal enabledelayedexpansion
REM =============================================================================
REM  TextEx — Complete Build Script
REM  Usage:  build.bat   (run from the project root)
REM  Output: dist\TextEx\TextEx.exe
REM =============================================================================

set PYTHON=.\venv\Scripts\python.exe
set PIP=.\venv\Scripts\pip.exe

echo.
echo ============================================================
echo  TextEx Build Script
echo ============================================================
echo.

REM ── Sanity checks ─────────────────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo [ERROR] Virtual environment not found at .\venv\
    echo         Run:  python -m venv venv
    echo               .\venv\Scripts\pip install -r requirements.txt
    pause & exit /b 1
)

REM ── Activate venv ─────────────────────────────────────────────────────────
call .\venv\Scripts\activate.bat

REM ── Step 1: Generate icon ─────────────────────────────────────────────────
echo [Step 1/3] Generating icon...
if not exist "assets\textex.ico" (
    %PYTHON% packaging\make_icon.py
    if errorlevel 1 (
        echo [WARNING] Icon generation failed. Build will continue without icon.
    ) else (
        echo           Icon written to assets\textex.ico
    )
) else (
    echo           assets\textex.ico already exists, skipping.
)

REM ── Step 2: PyInstaller ───────────────────────────────────────────────────
echo.
echo [Step 2/3] Running PyInstaller...
echo           This takes 3-10 minutes on first run (collecting PaddleOCR files).
echo.

%PYTHON% -m PyInstaller TextEx.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. Check the output above for details.
    pause & exit /b 1
)

REM ── Step 3: Verify output ─────────────────────────────────────────────────
echo.
echo [Step 3/3] Verifying output...

if not exist "dist\TextEx\TextEx.exe" (
    echo [ERROR] dist\TextEx\TextEx.exe was not created.
    pause & exit /b 1
)

REM Calculate approximate size
for /f "tokens=3" %%a in ('dir /s /a "dist\TextEx" ^| find "File(s)"') do set SIZE=%%a
echo           Output: dist\TextEx\TextEx.exe
echo           Total dist size: ~%SIZE% bytes

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Executable : dist\TextEx\TextEx.exe
echo  To create installer run: build_installer.bat
echo.
pause
