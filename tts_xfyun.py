"""
讯飞在线语音合成 (TTS) — WebSocket v2
"""
import websocket, hashlib, hmac, base64, json, time, ssl
from urllib.parse import urlencode, quote
from datetime import datetime
from wsgiref.handlers import format_date_time
from time import mktime


def create_url(api_key, api_secret):
    url = "wss://tts-api.xfyun.cn/v2/tts"
    # Must be current UTC time in RFC1123 format
    import calendar, time as _time
    date = format_date_time(calendar.timegm(_time.gmtime()))

    signature_origin = f"host: tts-api.xfyun.cn\ndate: {date}\nGET /v2/tts HTTP/1.1"
    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        msg=signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    signature_sha_base64 = base64.b64encode(signature_sha).decode()

    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature_sha_base64}"'
    )
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode()

    # Date must NOT be URL-encoded — use quote_via=quote to avoid encoding spaces/commas
    return url + "?authorization=" + quote(authorization) + "&date=" + quote(date) + "&host=tts-api.xfyun.cn"


def synthesize(text, voice, appid, api_key, api_secret, speed=50, pitch=50, volume=50):
    """Synthesize text to audio. Returns raw PCM bytes (or mp3 if supported)."""
    url = create_url(api_key, api_secret)
    audio_chunks = []
    done_event = {"done": False, "error": None}

    def on_message(ws, message):
        data = json.loads(message)
        code = data.get("code", -1)
        if code != 0:
            done_event["error"] = f"TTS error code {code}: {data.get('message', '')}"
            ws.close()
            return
        audio_b64 = data.get("data", {}).get("audio", "")
        if audio_b64:
            audio_chunks.append(base64.b64decode(audio_b64))
        status = data.get("data", {}).get("status", 1)
        if status == 2:
            ws.close()

    def on_open(ws):
        req = {
            "common": {"app_id": appid},
            "business": {
                "aue": "lame",   # MP3
                "auf": "audio/L16;rate=16000",
                "vcn": voice,
                "speed": speed,
                "volume": volume,
                "pitch": pitch,
                "tte": "UTF8"
            },
            "data": {
                "status": 2,
                "text": base64.b64encode(text.encode('utf-8')).decode()
            }
        }
        ws.send(json.dumps(req))

    def on_error(ws, error):
        done_event["error"] = str(error)

    def on_close(ws, *args):
        done_event["done"] = True

    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_open=on_open,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

    if done_event["error"]:
        raise RuntimeError(done_event["error"])

    return b"".join(audio_chunks)
