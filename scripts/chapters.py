"""章节识别与文件名规范化：把同一内容的 PDF 和 MP3 配对。"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"}

# 文件名中需要剔除的水印/冗余标记
_NOISE_PATTERNS = [
    re.compile(r"\[uivita\.com\]", re.IGNORECASE),
    re.compile(r"（音频", re.IGNORECASE),
    re.compile(r"\(\d+\)$"),  # 重复文件标记，如 "(1)"
]


def normalize_stem(filename: str) -> str:
    """从文件名提取规范化章节名（去掉扩展名、水印、重复标记）。"""
    stem = Path(filename).stem
    stem = unicodedata.normalize("NFC", stem)
    for pat in _NOISE_PATTERNS:
        stem = pat.sub("", stem)
    # 统一空白
    stem = re.sub(r"\s+", " ", stem).strip()
    # 去掉结尾多余标点/空白（同一章节的 PDF 与 MP3 命名常有结尾问号差异）
    stem = stem.strip(" .-？?！!。.")
    return stem


def collection_name(dirname: str) -> str:
    """从目录名提取资料名称：去掉前导编号和【完结】等标记。"""
    name = unicodedata.normalize("NFC", dirname)
    name = re.sub(r"【[^】]*】", "", name)  # 【完结】
    name = re.sub(r"^\d+[.、．]\s*", "", name)  # 164.
    name = name.strip(" .-")
    return name or dirname


def safe_dirname(name: str) -> str:
    """保证目录名在文件系统安全（macOS 不允许 '/'）。"""
    return name.replace("/", "／").strip()


def scan_source(source_dir: Path) -> dict[str, dict[str, Path]]:
    """扫描目录，返回 {章节名: {"pdf": Path, "audio": Path}}。

    同一章节可能只有 PDF 或只有音频。
    """
    chapters: dict[str, dict[str, Path]] = {}
    order: list[str] = []
    for p in sorted(source_dir.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in PDF_EXTS and ext not in AUDIO_EXTS:
            continue
        stem = normalize_stem(p.name)
        if stem not in chapters:
            chapters[stem] = {}
            order.append(stem)
        kind = "pdf" if ext in PDF_EXTS else "audio"
        # 若同类型重复（如 .MP3 与 .mp3 两份），保留文件较大者视为更完整
        if kind in chapters[stem]:
            if p.stat().st_size > chapters[stem][kind].stat().st_size:
                chapters[stem][kind] = p
        else:
            chapters[stem][kind] = p

    def sort_key(stem: str) -> tuple:
        m = re.match(r"(\d+)", stem)
        return (0, int(m.group(1)), stem) if m else (1, 0, stem)

    return {k: chapters[k] for k in sorted(order, key=sort_key)}
