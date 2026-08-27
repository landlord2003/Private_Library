@echo off
cd /d "%~dp0"
set PY=C:\Users\吴自强\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
echo ============================================
echo  私有图书馆 · 摘要修复（可续跑 · 不依赖盘符）
echo  仅 54 本摘要偏短，分钟级完成（需本机 Ollama）
echo  参数：
echo    --dry-run          只统计待修复数量，不调用 Ollama
echo    --limit 50         本次数量
echo    --model qwen2.5:7b 指定模型
echo    --retry            重试之前失败的
echo ============================================
"%PY%" "%~dp0summary_fix.py" %*
pause
