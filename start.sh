#!/bin/bash
set -e

echo "🎭 嘉骏15周年 AI双星登场 — 启动中..."
cd "$(dirname "$0")"

# 为避免跨机器复制导致的解释器损坏，始终重建本机 venv（快速且最稳）
echo "♻️ 重建本机虚拟环境..."
rm -rf venv
/usr/bin/python3 -m venv venv

venv/bin/python -m pip install -q --upgrade pip
venv/bin/python -m pip install -q -r requirements.txt

echo "✅ 打开浏览器：http://localhost:5001"
exec venv/bin/python app.py
