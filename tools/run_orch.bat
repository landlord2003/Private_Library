@echo off
setlocal
cd /d "%~dp0"

REM Locate python via %USERPROFILE% to avoid hardcoding the Chinese username
set "PY=python"
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" if exist "C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"

REM 等待此 PID(当前第4批元数据)结束后，编排器接管续批+摘要修复
set "ORCH_WAIT_PID=24672"

echo Using Python: %PY%
echo Launching orchestrator (detached, survives session end)...
start "" "%PY%" _orch_meta_summary.py
echo Orchestrator launched. Log: tools\_orch_meta_summary.log
