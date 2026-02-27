"""
阿里云TTS模块 — 嘉骏演示程序
支持 REST API 流式语音合成
"""
import os, json, requests
from dotenv import load_dotenv
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

load_dotenv()

AK_ID = os.getenv("ALIYUN_ACCESS_KEY_ID")
AK_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
APP_KEY = os.getenv("ALIYUN_NLS_APP_KEY")

_token_cache = {"token": None, "expire": 0}

def _get_token():
    import time
    now = int(time.time())
    if _token_cache["token"] and _token_cache["expire"] > now + 60:
        return _token_cache["token"]

    client = AcsClient(AK_ID, AK_SECRET, "cn-shanghai")
    req = CommonRequest()
    req.set_method("POST")
    req.set_domain("nls-meta.cn-shanghai.aliyuncs.com")
    req.set_version("2019-02-28")
    req.set_action_name("CreateToken")
    resp = json.loads(client.do_action_with_exception(req))
    token = resp["Token"]["Id"]
    expire = resp["Token"]["ExpireTime"]
    _token_cache["token"] = token
    _token_cache["expire"] = expire
    return token

# Voice options:
# aiqi    — 温柔女声（适合MuffinMac 姐姐）
# aijia   — 成熟女声
# aimei   — 甜美女声
# aitong  — 童声
# aiyue   — 活泼女声（适合MuffinUbuntu 妹妹）
# ruoxi   — 知性女声

VOICE_MAP = {
    "mac": "zhimiao_emo",  # 情感丰富稳重 = MuffinMac 姐姐
    "ubuntu": "aimei",     # 甜美可爱 = MuffinUbuntu 妹妹（Leon最终确认）
}

VOICE_PARAMS = {
    "mac":    {"speech_rate": 0,   "pitch_rate": 0},
    "ubuntu": {"speech_rate": 0, "pitch_rate": 0},  # 自然原速，最像真人
}

def synthesize(text: str, character: str = "ubuntu") -> bytes:
    """
    合成语音，返回MP3字节。
    character: "mac" | "ubuntu"
    """
    token = _get_token()
    voice = VOICE_MAP.get(character, "aiqi")

    url = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/tts"
    headers = {"X-NLS-Token": token, "Content-Type": "application/json"}
    params = VOICE_PARAMS.get(character, {"speech_rate": 0, "pitch_rate": 0})
    payload = {
        "appkey": APP_KEY,
        "text": text,
        "token": token,
        "format": "mp3",
        "sample_rate": 16000,
        "voice": voice,
        "speech_rate": params["speech_rate"],
        "pitch_rate": params["pitch_rate"],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Aliyun TTS error {resp.status_code}: {resp.text[:200]}")
    return resp.content


if __name__ == "__main__":
    # 快速测试
    print("Testing MuffinMac (aiqi)...")
    audio = synthesize("大家好，我是MuffinMac，很高兴在嘉骏十五周年庆典上和大家相遇！", "mac")
    with open("/tmp/test_mac.mp3", "wb") as f:
        f.write(audio)
    print(f"  OK: {len(audio)} bytes → /tmp/test_mac.mp3")

    print("Testing MuffinUbuntu (aiyue)...")
    audio = synthesize("嗨大家好！我是MuffinUbuntu，比姐姐活泼一点点，嘉骏十五周年快乐！", "ubuntu")
    with open("/tmp/test_ubuntu.mp3", "wb") as f:
        f.write(audio)
    print(f"  OK: {len(audio)} bytes → /tmp/test_ubuntu.mp3")
