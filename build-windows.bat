@echo off
REM Build Continuity Bridge for Windows

setlocal enabledelayedexpansion

REM Extract version from ale_merger_gui.py
for /f "tokens=2 delims==" %%i in ('findstr "^VERSION" ale_merger_gui.py') do (
    set VERSION=%%i
    set VERSION=!VERSION:"=!
    set VERSION=!VERSION: (Beta)=!
    set VERSION=!VERSION: =!
)

echo Building Continuity Bridge v%VERSION% for Windows...

REM Build
pyinstaller -y --clean continuity_bridge_win.spec

REM Rename EXE
move "dist\ContinuityBridge.exe" "dist\ContinuityBridge-%VERSION%.exe"

echo.
echo EXE created: dist\ContinuityBridge-%VERSION%.exe
echo.
echo Manual upload to GitHub:
echo   gh release view v%VERSION%
echo   gh release upload v%VERSION% "dist\ContinuityBridge-%VERSION%.exe" --clobber
echo.
