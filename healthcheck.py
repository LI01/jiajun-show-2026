#!/usr/bin/env python3
"""
嘉骏-show 一键自检脚本
运行: python3 healthcheck.py
"""
import sys, os, json, importlib

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results = []

def check(name, fn):
    try:
        msg = fn()
        print(f"{PASS} {name}: {msg}")
        results.append(("pass", name))
    except Exception as e:
        print(f"{FAIL} {name}: {e}")
        results.append(("fail", name, str(e)))

print("\n🧁 嘉骏-show 自检开始...\n")

# 1. Python 依赖
def check_deps():
    deps = ["flask", "requests", "dotenv", "edge_tts", "aliyunsdkcore"]
    missing = []
    for d in deps:
        try: importlib.import_module(d)
        except: missing.append(d)
    if missing:
        raise Exception(f"缺少: {', '.join(missing)} → pip install -r requirements.txt")
    return f"全部 {len(deps)} 个依赖已安装"

check("Python 依赖", check_deps)

# 2. .env 文件
def check_env():
    from dotenv import load_dotenv
    load_dotenv()
    missing = []
    for key in ["GEMINI_API_KEY", "ALIYUN_ACCESS_KEY_ID", "ALIYUN_ACCESS_KEY_SECRET", "ALIYUN_NLS_APP_KEY"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        raise Exception(f".env 缺少: {', '.join(missing)}")
    return ".env 配置完整"

check(".env 配置", check_env)

# 3. Gemini AI
def check_gemini():
    import requests
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise Exception("GEMINI_API_KEY 未设置")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
    r = requests.post(url, json={"contents":[{"role":"user","parts":[{"text":"hi"}]}]}, timeout=10)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text[:100]}")
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return f"AI响应正常: {text[:30]}..."

check("Gemini AI", check_gemini)

# 4. 阿里云 TTS
def check_aliyun_tts():
    sys.path.insert(0, os.path.dirname(__file__))
    from tts_aliyun import synthesize
    audio = synthesize("自检测试", "mac")
    if len(audio) < 1000:
        raise Exception(f"返回音频太小: {len(audio)} bytes")
    return f"阿里云TTS正常: {len(audio)} bytes"

check("阿里云 TTS", check_aliyun_tts)

# 5. edge-tts (fallback)
def check_edge_tts():
    import asyncio, edge_tts, tempfile
    async def _test():
        comm = edge_tts.Communicate("测试", "zh-CN-XiaoxiaoNeural")
        tmp = tempfile.mktemp(suffix=".mp3")
        await comm.save(tmp)
        size = os.path.getsize(tmp)
        os.unlink(tmp)
        return size
    size = asyncio.run(_test())
    if size < 500:
        raise Exception(f"音频太小: {size} bytes")
    return f"edge-tts正常: {size} bytes"

check("edge-tts 备用", check_edge_tts)

# 6. Flask 服务（如果已启动）
def check_server():
    import requests
    r = requests.get("http://127.0.0.1:5001/", timeout=3)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    return "服务运行中 http://127.0.0.1:5001"

check("Flask 服务", check_server)

# 汇总
print()
passed = sum(1 for r in results if r[0] == "pass")
failed = sum(1 for r in results if r[0] == "fail")
total = len(results)

if failed == 0:
    print(f"🎉 全部通过 {passed}/{total} — 可以开始表演了！")
else:
    print(f"{WARN} {passed}/{total} 通过，{failed} 项需要修复")
    print("\n修复建议:")
    for r in results:
        if r[0] == "fail":
            print(f"  • {r[1]}: {r[2]}")
print()
