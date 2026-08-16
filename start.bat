@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Private Lib

cd /d "%~dp0"
set "LIB_DIR=%~dp0"
set "LIB_DRIVE=%~d0"

echo ╔══════════════════════════════════╗
echo ║      📚 个人电子图书馆             ║
echo ╚══════════════════════════════════╝
echo.

:: 1. 检测 Python
echo [1/4] 检测 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ 未找到 Python
    echo   请从 https://www.python.org/downloads/ 下载安装
    echo   安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo   ✅ Python %%v

:: 2. 修正盘符（移动硬盘换电脑时盘符可能变化）
echo [2/4] 检查文件路径...
python -c "import sqlite3,os;db=sqlite3.connect('data/library.db');rows=db.execute(\"SELECT id,file_path FROM books WHERE file_path LIKE '%:%' LIMIT 1\").fetchall();db.close();old=rows[0][1][:2] if rows else None;new=os.path.abspath('.').split(':')[0]+':';print(f'原盘符:{old} 当前盘符:{new}');exit(0 if old==new or not old else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   盘符已变，自动修正中...
    python -c "import sqlite3,os;db=sqlite3.connect('data/library.db');books=db.execute(\"SELECT id,file_path FROM books WHERE file_path LIKE '%:%'\").fetchall();media=db.execute(\"SELECT id,file_path FROM media WHERE file_path LIKE '%:%'\").fetchall();new_drv=os.path.abspath('.').split(':')[0]+':';cnt=0;[(db.execute(f\"UPDATE books SET file_path=? WHERE id=?\",(new_drv+b[1][2:],b[0]),),cnt:=cnt+1) for b in books if os.path.exists(new_drv+b[1][2:])];[(db.execute(f\"UPDATE media SET file_path=? WHERE id=?\",(new_drv+m[1][2:],m[0]),),cnt:=cnt+1) for m in media if os.path.exists(new_drv+m[1][2:])];db.commit();print(f'  已修正 {cnt} 条路径');db.close()"
) else (
    echo   ✅ 路径正常
)

:: 3. 启动服务
echo [3/4] 启动服务器...
start "" http://localhost:8000
echo [4/4] 服务运行中...
echo.
echo   🌐 http://localhost:8000
echo   按 Ctrl+C 停止
echo.
python Private_Lib.py

pause
