@echo off
setlocal
title AI MEETING ASSISTANT - INSTALLATION VERIFICATION

cd /d "%~dp0"

echo ======================================================================
echo  AI MEETING ASSISTANT - INSTALLATION VERIFICATION
echo ======================================================================
echo.
echo Running diagnostic environment checks...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_setup.ps1"
set "VERIFY_STATUS=%ERRORLEVEL%"

echo.
if %VERIFY_STATUS% equ 0 (
    echo [OK] Verification finished successfully.
) else (
    echo [ERROR] Verification identified one or more issues (Exit Code: %VERIFY_STATUS%).
    echo Please review the action items displayed above or check verify_report.txt.
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %VERIFY_STATUS%

