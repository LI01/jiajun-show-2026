#!/bin/bash
echo "🎭 嘉骏15周年 AI双星登场 — 启动中..."
cd "$(dirname "$0")"
# 创建虚拟环境（如果没有）
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
venv/bin/pip install -q -r requirements.txt
echo "✅ 打开浏览器：http://localhost:5001"
venv/bin/python app.py
