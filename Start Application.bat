@echo off
setlocal
title AI MEETING ASSISTANT - START APPLICATION

cd /d "%~dp0"

echo ======================================================================
echo  AI MEETING ASSISTANT - STARTING APPLICATION
echo ======================================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_application.ps1"
set "APP_STATUS=%ERRORLEVEL%"

if %APP_STATUS% neq 0 (
    echo.
    echo [ERROR] Application could not be started (Exit Code: %APP_STATUS%).
    echo Please run "Verify Installation.bat" or review the diagnostic details above.
    echo.
    echo Press any key to close this window...
    pause >nul
)
exit /b %APP_STATUS%

