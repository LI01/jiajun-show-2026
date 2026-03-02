"""
三层 ASR 修正系统
================

第一层: 阿里云热词表 (hotwords.json) — 在 NLS 连接时传入，提升权重
第二层: 正则/映射表即时替换 — ASR 返回后立刻做确定性替换
第三层: LLM 语义修正 (仅最终结果) — 异步发送给 LLM 做语义校正

用法:
    from asr_corrections import load_hotwords, correct_interim, correct_final_async

    # 第一层：获取热词，在 RealtimeASR.start() 之前传入
    hotwords = load_hotwords()

    # 第二层：中间结果立刻替换
    text = correct_interim("加骏15周年")  # → "嘉骏15周年"

    # 第三层：最终结果异步 LLM 修正
    def on_llm_done(corrected_text):
        print("LLM 修正结果:", corrected_text)
    correct_final_async("识别结果原文", callback=on_llm_done)
"""

import os
import json
import re
import threading
import logging

import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ─── LLM 配置（复用 app.py 中的环境变量）────────────────────────────────────────
OPENAI_BASE    = os.environ.get("OPENAI_BASE", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "qwen-plus")

# hotwords.json 路径（与本文件同目录）
HOTWORDS_FILE = Path(__file__).parent / "hotwords.json"

# ═══════════════════════════════════════════════════════════════════════════════
# 第一层：热词表
# ═══════════════════════════════════════════════════════════════════════════════

def load_hotwords() -> list:
    """
    从 hotwords.json 加载热词列表。
    返回字符串列表，用于 RealtimeASR 的 hotwords 参数。
    """
    try:
        with open(HOTWORDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        words = data.get("hotwords", [])
        logger.info(f"[Corrections] 热词加载成功，共 {len(words)} 个")
        return words
    except FileNotFoundError:
        logger.warning(f"[Corrections] 未找到 hotwords.json，热词功能禁用")
        return []
    except Exception as e:
        logger.warning(f"[Corrections] 加载热词失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 第二层：映射表即时替换
# ═══════════════════════════════════════════════════════════════════════════════

# 确定性替换表 —— key: 错误写法, value: 正确写法
# 按从长到短排序，避免短词干扰长词匹配
CORRECTIONS_MAP = {
    # 嘉骏 相关
    "加骏":           "嘉骏",
    "佳骏":           "嘉骏",
    "嘉君":           "嘉骏",
    "家骏":           "嘉骏",

    # Leopard 相关
    "雷帕德":         "Leopard",
    "来帕德":         "Leopard",
    "来帕特":         "Leopard",
    "雷帕特":         "Leopard",
    "来巴德":         "Leopard",
    "雷巴德":         "Leopard",

    # Muffin 相关
    "马芬":           "Muffin",
    "玛芬":           "Muffin",
    "麦芬":           "Muffin",
    "马粉":           "Muffin",

    # MuffinMac
    "马芬Mac":        "MuffinMac",
    "马芬mac":        "MuffinMac",
    "玛芬Mac":        "MuffinMac",

    # MuffinUbuntu
    "马芬Ubuntu":     "MuffinUbuntu",
    "马芬ubuntu":     "MuffinUbuntu",
    "玛芬Ubuntu":     "MuffinUbuntu",

    # 产品型号
    "GS五百":         "GS500",
    "MS五百":         "MS500",
    "艾姆艾克斯五零一": "IMX501",
    "艾姆艾克斯501":  "IMX501",
    "IMX五零一":      "IMX501",
    "爱姆爱克斯五零一": "IMX501",

    # 人名
    "列翁":           "Leon",
    "里昂":           "Leon",
    "莱昂":           "Leon",

    # 品牌
    "sony":           "Sony",
    "SONY":           "Sony",

    # 技术词汇
    "星光极":         "星光级",
    "性光级":         "星光级",
    "形光级":         "星光级",
    "量率":           "良率",
    "良率率":         "良率",

    # 其他常见误识别
    "AglaiaSense":    "AglaiaSense",  # 保持不变
}

# 预编译正则（按 key 长度降序，先匹配长词）
_SORTED_CORRECTIONS = sorted(CORRECTIONS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
_PATTERNS = [
    (re.compile(re.escape(wrong)), right)
    for wrong, right in _SORTED_CORRECTIONS
]


def apply_corrections(text: str) -> str:
    """
    第二层：对文本应用映射表替换。
    对 interim 和 final 都生效，同步执行，速度极快。
    """
    for pattern, right in _PATTERNS:
        text = pattern.sub(right, text)
    return text


def correct_interim(text: str) -> str:
    """
    处理中间结果（第二层）。
    只做映射表替换，不做 LLM（中间结果频繁更新，LLM 太慢）。
    """
    return apply_corrections(text)


def correct_final(text: str) -> str:
    """
    处理最终结果（第二层，同步）。
    仅做映射表替换，LLM 修正请用 correct_final_async。
    """
    return apply_corrections(text)


# ═══════════════════════════════════════════════════════════════════════════════
# 第三层：LLM 语义修正（仅最终结果，异步）
# ═══════════════════════════════════════════════════════════════════════════════

# LLM prompt 模板
_LLM_PROMPT = (
    "以下是语音识别结果，请根据嘉骏15周年演出的上下文修正可能的错误词，"
    "只返回修正后的文本，不要解释：{text}"
)


def _call_llm(text: str) -> str:
    """
    调用 OpenAI 兼容 API 做语义修正。
    返回修正后文本；失败则返回原文。
    """
    if not OPENAI_BASE or not OPENAI_API_KEY:
        logger.debug("[Corrections] LLM 未配置，跳过第三层")
        return text

    prompt = _LLM_PROMPT.format(text=text)
    try:
        resp = requests.post(
            f"{OPENAI_BASE.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model":       OPENAI_MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  500,
                "temperature": 0.1,   # 低温度，保证确定性
            },
            timeout=10,
        )
        resp.raise_for_status()
        corrected = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"[Corrections] LLM 修正: '{text}' → '{corrected}'")
        return corrected
    except requests.Timeout:
        logger.warning("[Corrections] LLM 请求超时，返回原文")
        return text
    except Exception as e:
        logger.warning(f"[Corrections] LLM 修正失败: {e}，返回原文")
        return text


def correct_final_async(text: str, callback) -> None:
    """
    异步执行三层修正（第二层 + 第三层 LLM），完成后调用 callback(corrected_text)。
    callback: (text: str) -> None

    内部：
    1. 先做第二层映射替换（同步）
    2. 再发给 LLM 做语义修正（在后台线程，不阻塞主流程）
    3. LLM 完成后回调 callback
    """
    # 第二层先同步做
    pre_corrected = apply_corrections(text)

    def _run():
        final = _call_llm(pre_corrected)
        try:
            callback(final)
        except Exception as e:
            logger.error(f"[Corrections] 回调异常: {e}")

    t = threading.Thread(target=_run, daemon=True, name="asr-llm-correction")
    t.start()
