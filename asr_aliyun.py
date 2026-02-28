"""
阿里云 ASR 一句话识别模块 — 嘉骏演示程序
REST API: https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr
"""
import os, json, time, requests
from dotenv import load_dotenv

load_dotenv()

AK_ID = os.getenv("ALIYUN_ACCESS_KEY_ID")
AK_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
APP_KEY = os.getenv("ALIYUN_NLS_APP_KEY")

_token_cache = {"token": None, "expire": 0}

def _get_token():
    now = int(time.time())
    if _token_cache["token"] and _token_cache["expire"] > now + 60:
        return _token_cache["token"]
    try:
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkcore.request import CommonRequest
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
    except Exception as e:
        raise RuntimeError(f"Aliyun token error: {e}")


def recognize(audio_bytes: bytes, fmt: str = "wav", sample_rate: int = 16000) -> str:
    """
    一句话语音识别。
    audio_bytes: 音频二进制（WAV/PCM/OGG-OPUS/WEBM）
    fmt: 'wav' | 'pcm' | 'ogg-opus'
    sample_rate: 采样率（默认 16000）
    返回识别文本，失败抛异常。
    """
    token = _get_token()
    url = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr"
    params = {
        "appkey": APP_KEY,
        "format": fmt,
        "sample_rate": sample_rate,
        "enable_punctuation_prediction": "true",
        "enable_inverse_text_normalization": "true",
    }
    headers = {
        "X-NLS-Token": token,
        "Content-Type": "application/octet-stream",
    }
    resp = requests.post(url, params=params, headers=headers, data=audio_bytes, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"Aliyun ASR HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("status") != 20000000:
        raise RuntimeError(f"Aliyun ASR error: {data}")
    return data.get("result", "")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            audio = f.read()
        fmt = "wav" if sys.argv[1].endswith(".wav") else "pcm"
        print("识别结果:", recognize(audio, fmt=fmt))
    else:
        print("用法: python asr_aliyun.py test.wav")
