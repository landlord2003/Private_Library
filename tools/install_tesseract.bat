@echo off
REM 安装 Tesseract OCR + 中文包，解锁扫描版 PDF 抽取。以管理员或普通用户运行均可。
powershell -ExecutionPolicy Bypass -File "%~dp0install_tesseract.ps1"
pause
