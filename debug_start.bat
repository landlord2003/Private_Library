@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM Locate python via %USERPROFILE% to avoid hardcoding the Chinese username
set "PY=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"

echo Using Python: %PY%
echo Stopping old service on port 8000 (if any)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /i ":8000" ^| findstr /i "LISTENING"') do (
    echo   killing PID %%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 >nul

echo Starting Private_Lib.py, logging to start_err.log ...
"%PY%" Private_Lib.py > start_err.log 2>&1
echo.
echo [Process exited] Now opening start_err.log in Notepad.
echo   - If it shows "listening on ...8000", the server started OK.
echo   - If it shows a red error, copy that text and send it to me.
pause
notepad start_err.log
