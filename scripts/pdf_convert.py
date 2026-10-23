"""PDF → Markdown 转换。

- 文字版 PDF：pymupdf4llm 提取，保留标题/加粗/列表结构，逐页记录页码。
- 扫描版 PDF：整本文字极少时启用 RapidOCR 逐页识别（中文效果好于 Tesseract）。
- 个别纯图片页：明确标记，不编造内容。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pymupdf4llm

from markdown_utils import build_toc

# 单页可见文字少于此字符数视为"无文字页"
EMPTY_PAGE_THRESHOLD = 20
# 整本无文字页比例超过此值视为扫描版
SCANNED_RATIO = 0.6
# OCR 渲染分辨率
OCR_DPI = 200
# OCR 置信度低于此值的行明确标记
OCR_LOW_CONF = 0.6


@dataclass
class PdfResult:
    markdown: str
    page_count: int
    is_scanned: bool
    ocr_pages: list[int] = field(default_factory=list)
    image_pages: list[int] = field(default_factory=list)
    char_count: int = 0


def _detect(pdf_path: Path) -> tuple[int, list[int]]:
    """返回 (总页数, 无文字页码列表)。"""
    doc = pymupdf.open(pdf_path)
    empty = [
        i + 1
        for i in range(doc.page_count)
        if len(doc[i].get_text().strip()) < EMPTY_PAGE_THRESHOLD
    ]
    n = doc.page_count
    doc.close()
    return n, empty


_ocr_engine = None


def _get_ocr():
    """惰性加载 RapidOCR（模型较大，仅扫描版 PDF 需要）。"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_page(page) -> str:
    """对单页渲染图做 OCR，按阅读顺序拼接文本行。"""
    import numpy as np
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    result, _ = _get_ocr()(img)
    if not result:
        return ""
    lines: list[str] = []
    for _box, text, conf in result:
        text = text.strip()
        if not text:
            continue
        if conf < OCR_LOW_CONF:
            text = f"{text} ⚠️(OCR置信度低)"
        lines.append(text)
    return "\n\n".join(lines)


def _convert_scanned(pdf_path: Path, page_count: int) -> PdfResult:
    """扫描版：逐页 RapidOCR。"""
    doc = pymupdf.open(pdf_path)
    parts: list[str] = []
    ocr_pages: list[int] = []
    image_pages: list[int] = []
    for i in range(doc.page_count):
        page_no = i + 1
        text = _ocr_page(doc[i]).strip()
        if text:
            ocr_pages.append(page_no)
        else:
            image_pages.append(page_no)
            text = "> ⚠️ 本页为图片页，OCR 未识别到文字内容。"
        parts.append(f"{text}\n\n<!-- 页码: {page_no} / {page_count} -->")
    doc.close()
    body = "\n\n".join(parts)
    return PdfResult(
        markdown=body.rstrip() + "\n",
        page_count=page_count,
        is_scanned=True,
        ocr_pages=ocr_pages,
        image_pages=image_pages,
        char_count=len(body),
    )


def convert_pdf(pdf_path: Path) -> PdfResult:
    page_count, empty_pages = _detect(pdf_path)
    is_scanned = bool(page_count) and len(empty_pages) / page_count > SCANNED_RATIO

    if is_scanned:
        return _convert_scanned(pdf_path, page_count)

    chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)

    parts: list[str] = []
    ocr_pages: list[int] = []
    image_pages: list[int] = []
    for i, chunk in enumerate(chunks):
        page_no = i + 1
        text = chunk["text"].strip()
        if not text:
            if page_no in empty_pages:
                image_pages.append(page_no)
                text = "> ⚠️ 本页为图片页，未能提取到文字内容。"
            else:
                text = "> ⚠️ 本页未提取到文字。"
        elif page_no in empty_pages and is_scanned:
            ocr_pages.append(page_no)
        parts.append(f"{text}\n\n<!-- 页码: {page_no} / {page_count} -->")

    body = "\n\n".join(parts)
    toc = build_toc(body)
    header = ""
    if toc:
        header = f"## 目录\n\n{toc}\n\n---\n\n"
    markdown = header + body.rstrip() + "\n"
    return PdfResult(
        markdown=markdown,
        page_count=page_count,
        is_scanned=is_scanned,
        ocr_pages=ocr_pages,
        image_pages=image_pages,
        char_count=len(body),
    )
