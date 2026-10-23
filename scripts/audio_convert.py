"""MP3 → Markdown 转写（MLX Whisper，Apple Silicon 本地运行）。

- 逐句保留时间戳，按停顿聚合为段落，完整保留原话。
- 不总结、不改写；低置信度段落明确标记。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# 必须在 import mlx_whisper 之前设置：Xet CDN 在国内被阻断，回退普通 HTTPS
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import re  # noqa: E402

import mlx_whisper  # noqa: E402

from markdown_utils import fmt_timestamp  # noqa: E402

_CJK = r"一-鿿　-〿＀-￯"


def normalize_punctuation(text: str) -> str:
    """把中文语境中的半角标点恢复为全角（不影响数字小数点与英文缩写）。"""
    # 逗号/问号/叹号/分号：只要紧邻中文字符即转换
    text = re.sub(rf"(?<=[{_CJK}])\s*,\s*", "，", text)
    text = re.sub(rf",(?=[{_CJK}])", "，", text)
    text = re.sub(rf"(?<=[{_CJK}])\s*\?\s*", "？", text)
    text = re.sub(rf"\?(?=[{_CJK}])", "？", text)
    text = re.sub(rf"(?<=[{_CJK}])\s*!\s*", "！", text)
    text = re.sub(rf"!(?=[{_CJK}])", "！", text)
    text = re.sub(rf"(?<=[{_CJK}])\s*;\s*", "；", text)
    text = re.sub(rf";(?=[{_CJK}])", "；", text)
    # 冒号：中文语境转全角
    text = re.sub(rf"(?<=[{_CJK}])\s*:\s*", "：", text)
    text = re.sub(rf":(?=[{_CJK}])", "：", text)
    # 句号：句尾半角点（前面是中文、后面是中文/结尾）转全角；保留小数点
    text = re.sub(rf"(?<=[{_CJK}])\.\s*", "。", text)
    return text

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
# 段间停顿超过该秒数则另起一段
PARAGRAPH_GAP = 1.5
# 每段最长时长（秒）
PARAGRAPH_MAX = 120.0
# no_speech_prob 高于此值且平均对数概率过低 → 标记为低置信度
LOW_CONF_LOGPROB = -0.7
LOW_CONF_NOSPEECH = 0.6


@dataclass
class AudioResult:
    markdown: str
    duration: float
    segment_count: int
    low_confidence: list[str] = field(default_factory=list)
    model: str = DEFAULT_MODEL


def _group_segments(segments: list[dict]) -> list[list[dict]]:
    """按停顿/时长把 whisper 片段聚成段落。"""
    paragraphs: list[list[dict]] = []
    current: list[dict] = []
    for seg in segments:
        if current:
            gap = seg["start"] - current[-1]["end"]
            span = seg["end"] - current[0]["start"]
            if gap > PARAGRAPH_GAP or span > PARAGRAPH_MAX:
                paragraphs.append(current)
                current = []
        current.append(seg)
    if current:
        paragraphs.append(current)
    return paragraphs


def transcribe_audio(
    audio_path: Path,
    model: str = DEFAULT_MODEL,
    language: str = "zh",
    initial_prompt: str | None = None,
) -> AudioResult:
    prompt = initial_prompt or "以下是简体中文普通话讲座，口语表达，包含标点符号。"
    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=language,
        word_timestamps=False,
        verbose=False,
        initial_prompt=prompt,
        condition_on_previous_text=True,
    )
    segments = result.get("segments", [])
    duration = segments[-1]["end"] if segments else 0.0

    low_conf: list[str] = []
    lines: list[str] = []
    for para in _group_segments(segments):
        ts = fmt_timestamp(para[0]["start"])
        texts: list[str] = []
        para_low = False
        for seg in para:
            t = seg["text"].strip()
            if not t:
                continue
            texts.append(t)
            if (
                seg.get("avg_logprob", 0) < LOW_CONF_LOGPROB
                and seg.get("no_speech_prob", 0) > LOW_CONF_NOSPEECH
            ):
                para_low = True
        if not texts:
            continue
        body = normalize_punctuation("".join(texts))  # 中文无需空格连接
        mark = " ⚠️（此段音频清晰度低，转写可能不准确）" if para_low else ""
        if para_low:
            low_conf.append(ts)
        lines.append(f"**[{ts}]**{mark} {body}")

    markdown = "\n\n".join(lines) + "\n" if lines else "> ⚠️ 未能从音频中识别出语音内容。\n"
    return AudioResult(
        markdown=markdown,
        duration=duration,
        segment_count=len(segments),
        low_confidence=low_conf,
        model=model,
    )
