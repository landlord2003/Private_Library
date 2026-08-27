@echo off
cd /d "%~dp0"
set PY=C:\Users\吴自强\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
if not defined KG_VAULT (
  echo [提示] 未设置 KG_VAULT 环境变量，将尝试自动搜索 Obsidian Vault。
  echo        另一台电脑请在「系统环境变量」里设 KG_VAULT=该机的 Vault 路径，
  echo        本脚本在移动盘上通用，无需改代码。
)
echo ============================================
echo  私有图书馆 · 知识图谱生成（可续跑 · 不依赖盘符）
echo  双击=对全部分类跑 L1 结构层（默认200本/次）
echo  参数：
echo    --mode l1^|l2      L1结构(不需Ollama) / L2语义(需Ollama)
echo    --cat 分类名       只处理某分类（如 "人工智能与机器学习"）
echo    --limit 200        本次数量
echo    --vault 路径       指定 Vault（也可设 KG_VAULT 环境变量）
echo    --regen            清空图谱进度重跑
echo ============================================
"%PY%" "%~dp0kg_build.py" %*
pause
