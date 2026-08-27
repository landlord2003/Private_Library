@echo off
cd /d "%~dp0"
set PY=C:\Users\吴自强\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
echo ============================================
echo  私有图书馆 · 元数据补全（可续跑 · 不依赖盘符）
echo  双击=跑200本（fast模式，快速补年份+ISBN）
echo  参数：
echo    --status           看进度（不联网）
echo    --limit 500        本次跑多少本
echo    --mode full        同时补出版社+简介（慢，按需）
echo    --retry-skips      重试之前没匹配到的书
echo  说明：随时可停，下次接着跑，不白干。
echo ============================================
"%PY%" "%~dp0meta_complete.py" %*
pause
