@echo off
setlocal
title AI MEETING ASSISTANT - APPLICATION SETUP

cd /d "%~dp0"

echo ======================================================================
echo  AI MEETING ASSISTANT - APPLICATION SETUP
echo ======================================================================
echo.
echo Starting automated environment configuration...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
set "SETUP_STATUS=%ERRORLEVEL%"

echo.
if %SETUP_STATUS% equ 0 (
    echo [OK] Setup completed successfully.
) else (
    echo [ERROR] Setup encountered an issue (Exit Code: %SETUP_STATUS%).
    echo Please review the action items displayed above or check setup_log.txt.
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %SETUP_STATUS%

