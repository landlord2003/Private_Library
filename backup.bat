@echo off
chcp 65001 >nul
title 个人电子图书馆 - 备份

echo ========================================
echo        📦 个人电子图书馆 — 备份工具
echo ========================================
echo.

cd /d "%~dp0"

set BACKUP_DIR=%~dp0..\library-backup-%date:~0,4%%date:~5,2%%date:~8,2%

echo 正在备份到: %BACKUP_DIR%
echo.

:: 备份核心数据
xcopy "%~dp0data" "%BACKUP_DIR%\data\" /E /I /Y /Q

:: 备份核心代码
copy "%~dp0Private_Lib.py" "%BACKUP_DIR%\" /Y >nul
copy "%~dp0requirements.txt" "%BACKUP_DIR%\" /Y >nul
copy "%~dp0start.bat" "%BACKUP_DIR%\" /Y >nul
copy "%~dp0backup.bat" "%BACKUP_DIR%\" /Y >nul
copy "%~dp0library_config.json" "%BACKUP_DIR%\" /Y >nul 2>nul

:: 备份工具脚本
xcopy "%~dp0scripts" "%BACKUP_DIR%\scripts\" /E /I /Y /Q 2>nul

echo.
echo ✅ 备份完成！
echo    位置: %BACKUP_DIR%
echo.
pause
