@echo off
setlocal enabledelayedexpansion
REM =============================================================================
REM  TextEx — Installer Build Script
REM  Usage:   build_installer.bat   (run AFTER build.bat)
REM  Requires: Inno Setup 6  https://jrsoftware.org/isdl.php
REM  Output:  installer\TextEx-Setup-1.0.0.exe
REM =============================================================================

echo.
echo ============================================================
echo  TextEx Installer Build
echo ============================================================
echo.

REM ── Check PyInstaller output exists ───────────────────────────────────────
if not exist "dist\TextEx\TextEx.exe" (
    echo [ERROR] dist\TextEx\TextEx.exe not found.
    echo         Run build.bat first to create the executable.
    pause & exit /b 1
)

REM ── Locate Inno Setup compiler ────────────────────────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
    set ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe
)
if exist "C:\Program Files\Inno Setup 6\iscc.exe" (
    set ISCC=C:\Program Files\Inno Setup 6\iscc.exe
)

if "!ISCC!"=="" (
    echo [ERROR] Inno Setup 6 not found.
    echo         Download from: https://jrsoftware.org/isdl.php
    echo         Install it, then re-run this script.
    pause & exit /b 1
)

echo [INFO] Using Inno Setup: !ISCC!
echo.

REM ── Create installer output directory ─────────────────────────────────────
if not exist "installer" mkdir installer

REM ── Run Inno Setup compiler ───────────────────────────────────────────────
echo [Building] Compiling installer...
"!ISCC!" installer\TextEx.iss

if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup compilation failed.
    pause & exit /b 1
)

REM ── Verify ────────────────────────────────────────────────────────────────
if not exist "installer\TextEx-Setup-1.0.0.exe" (
    echo [ERROR] Expected installer\TextEx-Setup-1.0.0.exe was not created.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  INSTALLER BUILD COMPLETE
echo ============================================================
echo.
echo  Installer : installer\TextEx-Setup-1.0.0.exe
echo.
echo  Distribute this single file to end users.
echo  No Python installation required on target machines.
echo.
pause
