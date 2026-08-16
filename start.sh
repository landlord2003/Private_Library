#!/bin/bash
# Private Lib — 启动脚本 (Mac/Linux)

echo "========================================"
echo "         📚 Private Lib"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "Starting server..."
python3 Private_Lib.py
