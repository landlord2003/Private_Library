@echo off
chcp 65001 >nul
title 个人电子图书馆 - 备份 (robocopy 增量镜像)
cd /d "%~dp0"

:: ===================== 配置 =====================
:: 备份目标根目录（全量约需 620GB 空闲；只备数据库任意盘均可）
set "TARGET=E:\workbuddy\我的图书馆"
:: 是否镜像书籍大文件(约600GB)：yes=全量  /  no=只备数据库+代码
set "FULL=no"
:: 受管 Python（用于 SQLite 在线热备）
set "PY=C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe"
:: ================================================

echo ========================================
echo    📦 个人电子图书馆 备份
echo    目标: %TARGET%
echo ========================================
echo.

if not exist "%TARGET%" mkdir "%TARGET%"

:: 1) 数据库在线热备（不停服务，自动处理 WAL，保证一致性）
echo [1/3] 备份数据库 library.db (SQLite 在线热备)...
"%PY%" -c "import sqlite3; s=sqlite3.connect(r'data/library.db'); d=sqlite3.connect(r'%TARGET%/library.db'); s.backup(d); d.close(); s.close(); print('DB backup OK')"
if errorlevel 1 (echo ❌ 数据库备份失败，请检查路径 & goto :end)

:: 2) 代码与配置（小文件，直接覆盖）
echo [2/3] 备份代码与配置...
copy /Y "Private_Lib.py" "%TARGET%\" >nul
copy /Y "start.bat" "%TARGET%\" >nul
copy /Y "backup.bat" "%TARGET%\" >nul
copy /Y "library_config.json" "%TARGET%\" >nul 2>nul
copy /Y "README*" "%TARGET%\" >nul 2>nul
xcopy "scripts" "%TARGET%\scripts\" /E /I /Y /Q 2>nul

:: 3) 书籍大文件（增量镜像，可断点续传，不删目标已有文件）
if "%FULL%"=="yes" (
  echo [3/3] 镜像书籍 data/books (robocopy 增量, 首次较慢)...
  robocopy "data\books" "%TARGET%\data\books" /E /R:2 /W:5 /NFL /NDL /TEE /LOG:"backup_last.log"
) else (
  echo [3/3] 跳过书籍大文件（FULL=no）
)

echo.
echo ✅ 备份完成：%TARGET%
:end
pause
