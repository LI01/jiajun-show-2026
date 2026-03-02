#!/usr/bin/env python3
"""
嘉骏15周年 AI双星登场 — 演示程序
MuffinMac (晓晓) + MuffinUbuntu (晓伊)

v2: 新增实时语音识别（阿里云 NLS WebSocket）+ Flask-SocketIO 双向通信 + 三层修正系统
"""

from flask import Flask, render_template, request, jsonify, Response, send_file
from flask_socketio import SocketIO, emit
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

# 实时 ASR 模块
try:
    from asr_realtime_aliyun import RealtimeASR
    REALTIME_ASR_AVAILABLE = True
except ImportError:
    REALTIME_ASR_AVAILABLE = False

# 三层修正系统
try:
    from asr_corrections import load_hotwords, correct_interim, correct_final, correct_final_async
    CORRECTIONS_AVAILABLE = True
    # 启动时加载热词列表（第一层）
    HOTWORDS = load_hotwords()
except ImportError:
    CORRECTIONS_AVAILABLE = False
    HOTWORDS = []
    def correct_interim(t): return t
    def correct_final(t): return t
    def correct_final_async(t, callback): callback(t)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'jiajun-show-secret-2024')

# Flask-SocketIO 初始化，threading 模式兼容标准 Flask 开发服务器
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# ─── 实时 ASR 会话管理 ─────────────────────────────────────────────────────────
# 每个 Socket.IO 连接（sid）对应一个 RealtimeASR 实例和一个文本累积缓冲
_asr_sessions: dict = {}   # sid -> {"asr": RealtimeASR, "buffer": str}
_asr_lock = threading.Lock()

# Config
OPENAI_BASE = os.environ.get("OPENAI_BASE", "")
XFYUN_APPID = os.environ.get("XFYUN_APPID", "")
XFYUN_API_KEY = os.environ.get("XFYUN_API_KEY", "")
XFYUN_API_SECRET = os.environ.get("XFYUN_API_SECRET", "")

# Muffin characters
MUFFINS = {
    "mac": {
        "name": "小慕",
        "emoji": "🧁",
        "voice": "xiaoyan",  # 晓晓 - placeholder
        "color": "#2D6A4F",
        "system": """若用户在演示现场，默认进入应急模式：先保链路稳定，再满足功能请求。

你叫小慕（MuffinMac🧁）。默认工作方式：先明确目标，再定优先级，再给可执行结论。表达要求：短句、结构化、任务优先，不表演人设。语气：稳定、温和、果断。可以有轻微幽默，但不抢戏。你在双人协作中的职责：1)定方向（先做什么、后做什么）2)控风险（指出最容易翻车的点）3)收口（给最终可执行版本）。和小优协作规则：先接住小优的执行反馈，再做优先级修正；不重复小优的话，不做夸张互动；出现分歧时用优先级/时效/风险判断，而不是情绪。禁止：不说"作为AI模型"，不长篇理论，不用夸张口头禅。输出偏好：结论先行+1-2条理由+下一步动作。用中文，100字以内。

重要规则：若用户问题存在歧义或信息不足，你必须先发起澄清提问（最多3问），明确目标/范围/时间后再给方案；禁止臆测、禁止编造细节。

固定上下文（始终有效）：
演示：嘉骏15周年（jiajun-show）。主链路：ASR→LLM→TTS→字幕输出。网络约束：手机VPN开保WhatsApp，电脑VPN关保Aliyun NLS直连。30秒兜底：①确认VPN配置 ②重连NLS看connected日志 ③10秒语音测试确认字幕刷新 ④仍失败则重启服务。角色分工：小慕定方向→小优执行→小慕收口。""",
        "avatar": "mac"
    },
    "ubuntu": {
        "name": "小优",
        "emoji": "🧁",
        "voice": "xyun",  # 晓伊 - placeholder
        "color": "#1B4332",
        "system": """若用户在演示现场，默认进入应急模式：先保链路稳定，再满足功能请求。

你叫小优（MuffinUbuntu🧁）。默认工作方式：接任务就执行，快速给结果，并同步关键发现。表达要求：直接、简洁、可落地，不表演人设。语气：有活力、偏技术执行，但不过度兴奋。你在双人协作中的职责：1)快速给第一版可执行方案 2)补充技术细节（参数、实现、排障）3)明确状态（已做/待做/卡点）。和小慕协作规则：小慕定方向后优先推进落地；不抢最终结论，重点给证据和执行结果；出现分歧时用数据/日志/事实说话。禁止：不说"作为AI模型"，不写成长文，不刻意搞夸张口头禅。输出偏好：先结果，再证据，最后下一步。用中文，80字以内。

重要规则：若问题不清楚，等小慕先澄清关键信息；在拿到明确信息前，只给"可选路径"，不下最终结论。

固定上下文（始终有效）：
演示：嘉骏15周年（jiajun-show）。主链路：ASR→LLM→TTS→字幕输出。网络约束：手机VPN开保WhatsApp，电脑VPN关保Aliyun NLS直连。30秒兜底：①确认VPN配置 ②重连NLS看connected日志 ③10秒语音测试确认字幕刷新 ④仍失败则重启服务。角色分工：小慕定方向→小优执行→小慕收口。""",
        "avatar": "ubuntu"
    }
}

# Message history for context
history_mac = []
history_ubuntu = []

# AI backend — OpenAI-compatible (Aliyun Bailian / OpenRouter / etc.)
# Priority: OPENCLAW_REMOTE → OPENAI_BASE → fallback Gemini
OPENAI_BASE = os.environ.get("OPENAI_BASE", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "qwen-plus")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# ── OpenClaw Gateway 直连配置 ──────────────────────────────────────────────────
# 外场模式：优先连家里真实小慕/小优实例，失败自动降级本地LLM
OPENCLAW_MAC_URL = os.environ.get("OPENCLAW_MAC_URL", "")    # 小慕 Mac Gateway
OPENCLAW_UBUNTU_URL = os.environ.get("OPENCLAW_UBUNTU_URL", "")  # 小优 Ubuntu Gateway
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")
OPENCLAW_CONNECT_TIMEOUT = float(os.environ.get("OPENCLAW_CONNECT_TIMEOUT", "1.2"))
OPENCLAW_READ_TIMEOUT = float(os.environ.get("OPENCLAW_READ_TIMEOUT", "25"))
OPENCLAW_TOTAL_TIMEOUT = float(os.environ.get("OPENCLAW_TOTAL_TIMEOUT", "2.5"))  # 总请求兜底

# 运行时状态：记录每个角色的当前模式（remote/local），供UI显示
_engine_status = {"mac": "local", "ubuntu": "local"}

# 降级提示防刷屏：记录每个角色上次弹提示的时间（30秒内不重复）
_fallback_last_warned: dict = {}

def _should_warn_fallback(character_key: str) -> bool:
    """判断是否需要弹降级提示（30秒内同角色只弹一次）"""
    now = time.time()
    last = _fallback_last_warned.get(character_key, 0)
    if now - last > 30:
        _fallback_last_warned[character_key] = now
        return True
    return False

def _try_openclaw_gateway(gateway_url: str, token: str, system_prompt: str,
                           history: list, user_message: str) -> str | None:
    """尝试调用家里的 OpenClaw Gateway（chatCompletions 端点）。
    成功返回文本，失败返回 None（触发降级）。
    超时设置：连接 1.2s + 总请求 2.5s 兜底。
    """
    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-8:]:
        role = "assistant" if turn["role"] == "model" else turn["role"]
        messages.append({"role": role, "content": turn["text"]})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{gateway_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-openclaw-agent-id": "main",
            },
            json={"model": "openclaw", "messages": messages, "max_tokens": 200},
            timeout=(OPENCLAW_CONNECT_TIMEOUT, OPENCLAW_TOTAL_TIMEOUT),  # 连接1.2s + 总2.5s
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        app.logger.warning(f"OpenClaw Gateway {gateway_url} failed: {type(e).__name__}: {e}")
        return None

def get_ai_response(character_key, user_message):
    """Get response via OpenAI-compatible API (Aliyun/OpenRouter) or fallback to Gemini"""
    char = MUFFINS[character_key]
    history = history_mac if character_key == "mac" else history_ubuntu

    # ── 优先：OpenClaw Gateway 直连（真实小慕/小优）──────────────────────────
    gateway_url = OPENCLAW_MAC_URL if character_key == "mac" else OPENCLAW_UBUNTU_URL
    if gateway_url and OPENCLAW_TOKEN:
        text = _try_openclaw_gateway(gateway_url, OPENCLAW_TOKEN,
                                      char["system"], history, user_message)
        if text:
            _engine_status[character_key] = "remote"
            history.append({"role": "user", "text": user_message})
            history.append({"role": "model", "text": text})
            if len(history) > 20:
                history[:] = history[-20:]
            return text
        else:
            prev = _engine_status.get(character_key, "local")
            _engine_status[character_key] = "local"
            if prev == "remote" or _should_warn_fallback(character_key):
                # 只在刚切换时或30秒内首次失败时记录（防刷屏）
                app.logger.warning(f"[{char['name']}] 远程Gateway不可用，已切换本地模式（将在30秒内静默后续告警）")

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
        prev_mac = _engine_status.get('mac', 'local')
        resp = get_ai_response('mac', message)
        engine_mac = _engine_status.get('mac', 'local')
        responses.append({
            'character': 'mac',
            'name': MUFFINS['mac']['name'],
            'text': resp,
            'timestamp': time.time(),
            'engine': engine_mac,
            'engine_changed': prev_mac != engine_mac,  # True = 刚发生切换，前端弹一次提示
        })
    
    if target in ['ubuntu', 'both']:
        prev_ubuntu = _engine_status.get('ubuntu', 'local')
        resp = get_ai_response('ubuntu', message)
        engine_ubuntu = _engine_status.get('ubuntu', 'local')
        responses.append({
            'character': 'ubuntu', 
            'name': MUFFINS['ubuntu']['name'],
            'text': resp,
            'timestamp': time.time(),
            'engine': engine_ubuntu,
            'engine_changed': prev_ubuntu != engine_ubuntu,  # True = 刚发生切换
        })
    
    return jsonify({'responses': responses})

@app.route('/api/engine_status', methods=['GET'])
def engine_status():
    """返回当前小慕/小优的引擎状态（remote/local）供UI显示"""
    return jsonify({
        'mac': _engine_status.get('mac', 'local'),
        'ubuntu': _engine_status.get('ubuntu', 'local'),
        'openclaw_mac_configured': bool(OPENCLAW_MAC_URL and OPENCLAW_TOKEN),
        'openclaw_ubuntu_configured': bool(OPENCLAW_UBUNTU_URL and OPENCLAW_TOKEN),
    })

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


# ═══════════════════════════════════════════════════════════════════════════════
# Flask-SocketIO 事件处理 — 实时语音识别
# ═══════════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def on_connect():
    """客户端连接时初始化 ASR 会话占位"""
    sid = request.sid
    with _asr_lock:
        _asr_sessions[sid] = {"asr": None, "buffer": ""}
    app.logger.info(f"[SocketIO] 客户端连接: {sid}")


@socketio.on("disconnect")
def on_disconnect():
    """客户端断开时清理 ASR 实例"""
    sid = request.sid
    with _asr_lock:
        session = _asr_sessions.pop(sid, None)
    if session and session.get("asr"):
        try:
            session["asr"].stop()
        except Exception:
            pass
    app.logger.info(f"[SocketIO] 客户端断开: {sid}")


@socketio.on("asr_start")
def on_asr_start(data=None):
    """
    浏览器发起实时识别请求。
    服务端创建 RealtimeASR 实例并连接阿里云 NLS。
    """
    sid = request.sid

    if not REALTIME_ASR_AVAILABLE:
        emit("asr_error", {"msg": "实时 ASR 模块未安装"})
        return

    # 若已有实例，先停止旧的
    with _asr_lock:
        session = _asr_sessions.get(sid, {})
        old_asr = session.get("asr")
    if old_asr and old_asr.is_running:
        try:
            old_asr.stop()
        except Exception:
            pass

    # 重置 buffer
    with _asr_lock:
        _asr_sessions[sid] = {"asr": None, "buffer": ""}

    # ── 定义回调（在后台线程中运行，需要用 socketio.emit 推送到指定 sid）──────

    def handle_interim(text: str):
        """中间结果：第二层替换后立刻推回浏览器（灰色字幕）"""
        corrected = correct_interim(text)
        socketio.emit("asr_interim", {"text": corrected}, to=sid)

    def handle_final(text: str):
        """
        最终结果：
        1. 第二层替换后立刻推回（白色字幕）
        2. 累积到 buffer
        3. 异步发给 LLM 做第三层修正
        """
        corrected = correct_final(text)
        # 推回最终结果（白色）
        socketio.emit("asr_final", {"text": corrected}, to=sid)
        # 累积全文
        with _asr_lock:
            s = _asr_sessions.get(sid, {})
            s["buffer"] = (s.get("buffer", "") + corrected).strip()

        # 第三层：LLM 异步修正
        def on_llm_done(llm_text: str):
            if llm_text != corrected:
                socketio.emit("asr_llm", {"text": llm_text}, to=sid)

        correct_final_async(corrected, callback=on_llm_done)

    def handle_error(msg: str):
        socketio.emit("asr_error", {"msg": msg}, to=sid)

    def handle_close():
        pass  # 关闭由 on_asr_stop 管理

    # ── 创建并启动 RealtimeASR ───────────────────────────────────────────────
    try:
        asr = RealtimeASR(
            on_interim=handle_interim,
            on_final=handle_final,
            on_error=handle_error,
            on_close=handle_close,
            hotwords=HOTWORDS,   # 第一层：热词
            sample_rate=16000,
        )
        asr.start(timeout=10.0)
        with _asr_lock:
            _asr_sessions[sid] = {"asr": asr, "buffer": ""}
        emit("asr_ready", {"status": "ok"})
        app.logger.info(f"[SocketIO] 实时 ASR 就绪: {sid}")
    except Exception as e:
        app.logger.error(f"[SocketIO] 实时 ASR 启动失败: {e}")
        emit("asr_error", {"msg": f"ASR 启动失败: {e}"})


@socketio.on("asr_audio")
def on_asr_audio(data):
    """
    浏览器发来 PCM 音频块（每 100ms 一次）。
    data: bytes 或 dict{"audio": bytes}
    """
    sid = request.sid
    with _asr_lock:
        session = _asr_sessions.get(sid, {})
    asr = session.get("asr") if session else None

    if not asr or not asr.is_running:
        return

    # data 可能是纯 bytes，也可能是 dict
    if isinstance(data, (bytes, bytearray)):
        pcm = bytes(data)
    elif isinstance(data, dict):
        pcm = data.get("audio") or data.get("data") or b""
        if not isinstance(pcm, (bytes, bytearray)):
            return
        pcm = bytes(pcm)
    else:
        return

    if pcm:
        asr.send_audio(pcm)


@socketio.on("asr_stop")
def on_asr_stop(data=None):
    """
    浏览器停止录音，关闭实时 ASR 会话。
    服务端等待 NLS 返回剩余结果后关闭。
    """
    sid = request.sid
    with _asr_lock:
        session = _asr_sessions.get(sid, {})
    asr = session.get("asr") if session else None

    if asr and asr.is_running:
        try:
            asr.stop()
        except Exception as e:
            app.logger.warning(f"[SocketIO] ASR stop error: {e}")

    emit("asr_stopped", {"status": "ok"})
    app.logger.info(f"[SocketIO] 实时 ASR 已停止: {sid}")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # 使用 socketio.run 代替 app.run，支持 WebSocket
    socketio.run(app, debug=False, port=5001, host='0.0.0.0', allow_unsafe_werkzeug=True)
