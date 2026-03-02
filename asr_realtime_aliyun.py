"""
阿里云实时语音识别模块 - WebSocket 流式
NLS SpeechTranscriber API
URL: wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1

支持中间结果（interim）和最终结果（final），
复用 asr_aliyun.py 的 _get_token() 逻辑。
"""

import os
import json
import time
import uuid
import threading
import logging

import websocket
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 环境变量（与 asr_aliyun.py 保持一致）
AK_ID     = os.getenv("ALIYUN_ACCESS_KEY_ID")
AK_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
APP_KEY   = os.getenv("ALIYUN_NLS_APP_KEY")

# Token 缓存（与 asr_aliyun.py 共享逻辑，独立缓存）
_token_cache = {"token": None, "expire": 0}


def _get_token() -> str:
    """获取阿里云 NLS 访问 Token（带过期缓存）"""
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
        logger.info("[RealtimeASR] Token 刷新成功")
        return token
    except Exception as e:
        raise RuntimeError(f"Aliyun token error: {e}")


class RealtimeASR:
    """
    阿里云实时语音识别客户端（WebSocket 流式）

    使用方式:
        asr = RealtimeASR(
            on_interim=lambda text: print("中间:", text),
            on_final=lambda text: print("最终:", text),
            hotwords=["嘉骏", "Leopard", "IMX501"],
        )
        asr.start()          # 连接 NLS 并发送 StartTranscription
        asr.send_audio(pcm)  # 发送 PCM 二进制数据（可多次调用）
        asr.stop()           # 发送 StopTranscription 并关闭连接
    """

    NLS_URL = "wss://nls-gateway-cn-shanghai.aliyuncs.com/ws/v1"

    def __init__(
        self,
        on_interim=None,     # 中间结果回调(text: str) -> None
        on_final=None,       # 最终结果回调(text: str) -> None
        on_error=None,       # 错误回调(msg: str) -> None
        on_close=None,       # 连接关闭回调() -> None
        hotwords=None,       # 热词列表
        sample_rate: int = 16000,
    ):
        self.on_interim  = on_interim
        self.on_final    = on_final
        self.on_error    = on_error
        self._on_close   = on_close
        self.hotwords    = hotwords or []
        self.sample_rate = sample_rate

        self._ws        = None          # WebSocket 连接对象
        self._task_id   = None          # 本次任务 ID
        self._lock      = threading.Lock()

        # 连接状态事件
        self._connected = threading.Event()
        self._started   = threading.Event()
        self._running   = False         # 是否正在运行

    # ─── 公共接口 ──────────────────────────────────────────────────────────────

    def start(self, timeout: float = 10.0):
        """
        启动实时识别：连接 WebSocket 并发送 StartTranscription。
        timeout: 等待连接和识别启动的超时秒数。
        """
        self._task_id = str(uuid.uuid4()).replace("-", "")
        token = _get_token()
        url = f"{self.NLS_URL}?token={token}&appkey={APP_KEY}"

        # ── 定义 WebSocket 回调 ────────────────────────────────────────────────
        def _on_open(ws):
            logger.info("[RealtimeASR] WebSocket 连接已建立")
            self._connected.set()
            self._send_start_transcription()

        def _on_message(ws, message):
            """处理服务端消息"""
            try:
                msg    = json.loads(message)
                header = msg.get("header", {})
                name   = header.get("name", "")

                if name == "TranscriptionStarted":
                    # 识别会话已在服务端启动，可以开始发送音频
                    logger.info("[RealtimeASR] 识别已启动，可发送音频")
                    self._started.set()

                elif name == "TranscriptionResultChanged":
                    # 中间结果（句子尚未结束）
                    result = msg.get("payload", {}).get("result", "")
                    if result and self.on_interim:
                        self.on_interim(result)

                elif name == "SentenceEnd":
                    # 句子结束，最终结果
                    result = msg.get("payload", {}).get("result", "")
                    if result and self.on_final:
                        self.on_final(result)

                elif name == "TranscriptionCompleted":
                    # 全部识别完成（收到 StopTranscription 后服务端发送）
                    logger.info("[RealtimeASR] 识别完成")

                elif name == "TaskFailed":
                    # 任务失败
                    status_msg = header.get("status_message", "unknown error")
                    logger.error(f"[RealtimeASR] 任务失败: {status_msg}")
                    if self.on_error:
                        self.on_error(f"ASR 任务失败: {status_msg}")

            except Exception as e:
                logger.error(f"[RealtimeASR] 消息处理异常: {e}")

        def _on_error(ws, error):
            logger.error(f"[RealtimeASR] WebSocket 错误: {error}")
            if self.on_error:
                self.on_error(str(error))

        def _on_close(ws, code, msg):
            logger.info(f"[RealtimeASR] WebSocket 关闭: {code} {msg}")
            self._running = False
            if self._on_close:
                self._on_close()

        # ── 创建 WebSocketApp ─────────────────────────────────────────────────
        self._ws = websocket.WebSocketApp(
            url,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        self._running = True
        self._connected.clear()
        self._started.clear()

        # 在后台线程中运行 WebSocket，保持 ping 心跳
        ws_thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={"ping_interval": 5, "ping_timeout": 3},
            daemon=True,
            name="aliyun-nls-ws",
        )
        ws_thread.start()

        # 等待连接和识别启动
        if not self._connected.wait(timeout=timeout):
            self._running = False
            raise TimeoutError("WebSocket 连接超时（可能是网络问题或 Token 无效）")
        if not self._started.wait(timeout=5.0):
            self._running = False
            raise TimeoutError("识别启动超时（AppKey 可能有误）")

        logger.info("[RealtimeASR] 实时识别就绪")

    def send_audio(self, pcm_bytes: bytes):
        """
        发送 PCM-16bit-mono 音频数据块（可多次调用，每次 100ms 左右）。
        pcm_bytes: 原始 PCM 二进制数据
        """
        if not self._ws or not self._running:
            return
        try:
            with self._lock:
                # opcode=0x2 表示二进制帧
                self._ws.send(pcm_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
        except Exception as e:
            logger.warning(f"[RealtimeASR] 发送音频失败: {e}")

    def stop(self):
        """停止识别，发送 StopTranscription，等待服务端完成并关闭连接。"""
        if not self._ws:
            return
        try:
            self._send_stop_transcription()
            # 给服务端一点时间处理剩余音频
            time.sleep(0.8)
        except Exception as e:
            logger.warning(f"[RealtimeASR] 发送 StopTranscription 失败: {e}")
        finally:
            self._running = False
            try:
                self._ws.close()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        """是否处于活动状态"""
        return self._running

    # ─── 私有方法 ──────────────────────────────────────────────────────────────

    def _make_header(self, name: str) -> dict:
        """构造 NLS 消息头"""
        return {
            "message_id": str(uuid.uuid4()).replace("-", ""),
            "task_id":    self._task_id,
            "namespace":  "SpeechTranscriber",
            "name":       name,
            "appkey":     APP_KEY,
        }

    def _send_start_transcription(self):
        """发送 StartTranscription 控制指令"""
        payload = {
            "sample_rate":                     self.sample_rate,
            "format":                          "pcm",
            "enable_punctuation_prediction":   True,   # 标点预测
            "enable_intermediate_result":      True,   # 中间结果
            "enable_inverse_text_normalization": True, # 数字规范化
        }

        # 热词支持：以空格分隔的中文/英文热词字符串
        # 阿里云 SpeechTranscriber 通过 hotword_list 字段传递内联热词
        if self.hotwords:
            # 过滤纯 ASCII 热词（英文），与中文热词分开处理
            cn_words = [w for w in self.hotwords if any('\u4e00' <= c <= '\u9fff' for c in w)]
            en_words = [w for w in self.hotwords if not any('\u4e00' <= c <= '\u9fff' for c in w)]
            # 合并成空格分隔字符串
            hotword_str = " ".join(cn_words + en_words)
            if hotword_str.strip():
                payload["hotword_list"] = hotword_str
                logger.debug(f"[RealtimeASR] 热词: {hotword_str}")

        msg = {"header": self._make_header("StartTranscription"), "payload": payload}
        self._ws.send(json.dumps(msg))

    def _send_stop_transcription(self):
        """发送 StopTranscription 控制指令"""
        msg = {"header": self._make_header("StopTranscription"), "payload": {}}
        self._ws.send(json.dumps(msg))
