@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Private Lib - Restart

cd /d "%~dp0"

echo ╔════════════════════════════════════╗
echo ║   📚 Private Lib 重启工具            ║
echo ╚════════════════════════════════════╝
echo.

:: 0. 检测 python（缺失则明确提示，不闪退）
echo [0/3] 检测 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ 未找到 python 命令
    echo   请安装 Python 并勾选 "Add Python to PATH": https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo   ✅ Python %%v

:: 1. 关闭残留进程（防止端口冲突导致启动即崩溃闪退）
echo [1/3] 关闭残留服务进程...
taskkill /f /im python.exe >nul 2>&1
if %errorlevel%==0 (echo   ✅ 已关闭旧进程) else (echo   ℹ️  当前无 python 进程)
timeout /t 1 >nul

:: 2. 设置环境变量
echo [2/3] 设置环境变量...
set "LIB_HOST=0.0.0.0"
set "LIB_METADATA_ONLINE=1"
echo   LIB_HOST=%LIB_HOST%
echo   LIB_METADATA_ONLINE=%LIB_METADATA_ONLINE%

:: 3. 启动服务（前台运行，关闭此窗口即停止）
echo [3/3] 启动服务（黑窗口请勿关闭）...
echo.
start "" http://localhost:8000
python Private_Lib.py

echo.
echo 服务已停止。
pause
