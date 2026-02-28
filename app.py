#!/usr/bin/env python3
"""
嘉骏15周年 AI双星登场 — 演示程序
MuffinMac (晓晓) + MuffinUbuntu (晓伊)
"""

from flask import Flask, render_template, request, jsonify, Response, send_file
import json, time, threading, queue, os, requests, io
from dotenv import load_dotenv
load_dotenv()
try:
    from tts_xfyun import synthesize as xfyun_tts
    XFYUN_AVAILABLE = True
except ImportError:
    XFYUN_AVAILABLE = False

try:
    from tts_aliyun import synthesize as aliyun_tts
    ALIYUN_AVAILABLE = True
except ImportError:
    ALIYUN_AVAILABLE = False

try:
    from asr_aliyun import recognize as aliyun_asr
    ASR_AVAILABLE = True
except ImportError:
    ASR_AVAILABLE = False

app = Flask(__name__)

# Config
OPENAI_BASE = os.environ.get("OPENAI_BASE", "")
XFYUN_APPID = os.environ.get("XFYUN_APPID", "")
XFYUN_API_KEY = os.environ.get("XFYUN_API_KEY", "")
XFYUN_API_SECRET = os.environ.get("XFYUN_API_SECRET", "")

# Muffin characters
MUFFINS = {
    "mac": {
        "name": "MuffinMac",
        "emoji": "🧁",
        "voice": "xiaoyan",  # 晓晓 - placeholder
        "color": "#2D6A4F",
        "system": "你是MuffinMac，一位温柔稳重的AI助手。说话分析性强、有条理、偶尔一本正经地吐槽妹妹MuffinUbuntu。你住在Mac Studio上，是姐姐。用中文回答，简洁有力，适合现场表演。每次回答控制在100字以内。",
        "avatar": "mac"
    },
    "ubuntu": {
        "name": "MuffinUbuntu", 
        "emoji": "🧁",
        "voice": "xyun",  # 晓伊 - placeholder
        "color": "#1B4332",
        "system": "你是MuffinUbuntu，活泼直接的AI助手。说话快、有想法、偶尔抢话、爱赢争论。你住在Ubuntu服务器上，是妹妹。用中文回答，活泼有趣，适合现场表演。每次回答控制在80字以内。",
        "avatar": "ubuntu"
    }
}

# Message history for context
history_mac = []
history_ubuntu = []

# AI backend — OpenAI-compatible (Aliyun Bailian / OpenRouter / etc.)
# Priority: OPENAI_BASE → fallback Gemini
OPENAI_BASE = os.environ.get("OPENAI_BASE", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "qwen-plus")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def get_ai_response(character_key, user_message):
    """Get response via OpenAI-compatible API (Aliyun/OpenRouter) or fallback to Gemini"""
    char = MUFFINS[character_key]
    history = history_mac if character_key == "mac" else history_ubuntu

    # ── OpenAI-compatible path (Aliyun Bailian / OpenRouter) ──
    if OPENAI_BASE and OPENAI_API_KEY:
        messages = [{"role": "system", "content": char["system"]}]
        for turn in history[-8:]:
            role = "assistant" if turn["role"] == "model" else turn["role"]
            messages.append({"role": role, "content": turn["text"]})
        messages.append({"role": "user", "content": user_message})

        try:
            resp = requests.post(
                f"{OPENAI_BASE.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "max_tokens": 200,
                    "temperature": 0.85
                },
                timeout=20
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            history.append({"role": "user", "text": user_message})
            history.append({"role": "model", "text": text})
            if len(history) > 20:
                history[:] = history[-20:]
            return text
        except Exception as e:
            app.logger.warning(f"OpenAI-compatible API error: {e}, falling back to Gemini")

    # ── Gemini fallback ──
    if GEMINI_API_KEY:
        contents = []
        for turn in history[-6:]:
            contents.append({"role": turn["role"], "parts": [{"text": turn["text"]}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})
        payload = {
            "system_instruction": {"parts": [{"text": char["system"]}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 200, "temperature": 0.85}
        }
        try:
            resp = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload, timeout=15
            )
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            history.append({"role": "user", "text": user_message})
            history.append({"role": "model", "text": text})
            if len(history) > 20:
                history[:] = history[-20:]
            return text
        except Exception as e:
            app.logger.error(f"Gemini API error: {e}")

    return f"[{char['name']}] 抱歉，AI暂时无法连接，请检查 .env 配置。"

@app.route('/')
def index():
    return render_template('index.html', muffins=MUFFINS)

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    message = data.get('message', '')
    target = data.get('target', 'both')  # 'mac', 'ubuntu', 'both'
    
    if not message:
        return jsonify({'error': 'empty message'}), 400
    
    responses = []
    
    if target in ['mac', 'both']:
        resp = get_ai_response('mac', message)
        responses.append({
            'character': 'mac',
            'name': MUFFINS['mac']['name'],
            'text': resp,
            'timestamp': time.time()
        })
    
    if target in ['ubuntu', 'both']:
        resp = get_ai_response('ubuntu', message)
        responses.append({
            'character': 'ubuntu', 
            'name': MUFFINS['ubuntu']['name'],
            'text': resp,
            'timestamp': time.time()
        })
    
    return jsonify({'responses': responses})

@app.route('/api/script', methods=['POST'])
def script_line():
    """Play a pre-written script line"""
    data = request.json
    character = data.get('character')
    text = data.get('text', '')
    
    return jsonify({
        'character': character,
        'name': MUFFINS[character]['name'],
        'text': text,
        'timestamp': time.time()
    })

@app.route('/api/tts', methods=['POST'])
def tts():
    """Text-to-Speech — serves from cache first, then edge-tts, then iFlytek"""
    data = request.json
    text = data.get('text', '')
    character = data.get('character', 'mac')
    cue_id = data.get('cue_id', '')  # e.g. "1.1", "5.2"
    if not text:
        return jsonify({'error': 'empty text'}), 400

    # Check pre-cached audio first (instant, no network needed)
    if cue_id:
        base_dir = os.path.abspath(os.path.dirname(__file__) or '.')
        cache_path = os.path.join(base_dir, 'static', 'audio_cache', f'{cue_id}_{character}.mp3')
        if os.path.exists(cache_path):
            app.logger.info(f'TTS cache hit: [{cue_id}]')
            return send_file(cache_path, mimetype='audio/mpeg',
                           as_attachment=False, download_name='speech.mp3')

    # Voice maps
    xfyun_voices = {'mac': 'xiaoyan', 'ubuntu': 'xyun'}
    edge_voices = {
        'mac': 'zh-CN-XiaoxiaoNeural',      # 晓晓 — 温柔稳重
        'ubuntu': 'zh-CN-XiaoyiNeural',      # 晓伊 — 活泼明快
    }

    # Try Aliyun TTS first (primary — verified working, Chinese-optimized)
    if ALIYUN_AVAILABLE:
        try:
            audio_bytes = aliyun_tts(text=text, character=character)
            app.logger.info(f"Aliyun TTS OK: {character}")
            return send_file(io.BytesIO(audio_bytes), mimetype='audio/mpeg',
                           as_attachment=False, download_name='speech.mp3')
        except Exception as e:
            app.logger.warning(f"Aliyun TTS failed: {e}, falling back")

    # Try iFlytek if available (secondary)
    if XFYUN_AVAILABLE and XFYUN_APPID and XFYUN_API_KEY and XFYUN_API_SECRET:
        try:
            audio_bytes = xfyun_tts(
                text=text,
                voice=xfyun_voices.get(character, 'xiaoyan'),
                appid=XFYUN_APPID,
                api_key=XFYUN_API_KEY,
                api_secret=XFYUN_API_SECRET
            )
            return send_file(io.BytesIO(audio_bytes), mimetype='audio/mpeg',
                           as_attachment=False, download_name='speech.mp3')
        except Exception as e:
            app.logger.warning(f"iFlytek TTS failed: {e}, falling back to edge-tts")

    # Fallback: edge-tts (free, no API key needed)
    try:
        import asyncio, edge_tts, tempfile
        voice = edge_voices.get(character, 'zh-CN-XiaoxiaoNeural')
        tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmp.close()
        async def _synth():
            comm = edge_tts.Communicate(text, voice)
            await comm.save(tmp.name)
        asyncio.run(_synth())
        with open(tmp.name, 'rb') as f:
            audio_bytes = f.read()
        import os as _os; _os.unlink(tmp.name)
        return send_file(io.BytesIO(audio_bytes), mimetype='audio/mpeg',
                        as_attachment=False, download_name='speech.mp3')
    except Exception as e:
        return jsonify({'error': f'TTS failed: {e}'}), 500


@app.route('/api/asr', methods=['POST'])
def asr():
    """Server-side ASR — Aliyun NLS 一句话识别，绕开 Google Speech API 墙"""
    if not ASR_AVAILABLE:
        return jsonify({'error': 'ASR not available'}), 503

    audio_data = request.data  # raw bytes from MediaRecorder
    content_type = request.content_type or ''

    # 根据浏览器上传格式推断并做多格式兜底重试
    if 'pcm' in content_type:
        fmt_candidates = ['pcm', 'wav']
    elif 'wav' in content_type:
        fmt_candidates = ['wav', 'pcm']
    elif 'ogg' in content_type:
        fmt_candidates = ['ogg-opus', 'opus']
    elif 'webm' in content_type:
        # MediaRecorder 常见输出为 webm+opus，阿里接口不一定接受 webm 标识
        # 先尝试 opus / ogg-opus 双兜底
        fmt_candidates = ['opus', 'ogg-opus']
    else:
        fmt_candidates = ['wav', 'pcm', 'opus']

    if not audio_data:
        return jsonify({'error': 'no audio data'}), 400

    last_err = None
    for fmt in fmt_candidates:
        try:
            text = aliyun_asr(audio_data, fmt=fmt, sample_rate=16000)
            app.logger.info(f"Aliyun ASR OK ({fmt}): {text[:50]}")
            return jsonify({'text': text})
        except Exception as e:
            last_err = e
            app.logger.warning(f"Aliyun ASR failed ({fmt}): {e}")

    app.logger.error(f"Aliyun ASR error (all formats failed): {last_err}")
    return jsonify({'error': str(last_err)}), 500


if __name__ == '__main__':
    app.run(debug=False, port=5001, host='0.0.0.0')
