#!/usr/bin/env python3
"""中文 PDF + MP3 → Markdown 批量转换入口。

用法：
    python scripts/convert.py --source "/path/资料目录" [--source "..."] [选项]

选项：
    --source DIR        资料目录（可多次指定）；不指定时读取 scripts/sources.txt
    --output DIR        输出根目录（默认: <项目>/output）
    --only {pdf,audio}  只转换某一类
    --force             忽略增量状态，强制重转
    --retry-failed      只重试之前失败的文件
    --model REPO        Whisper 模型（默认 mlx-community/whisper-large-v3-turbo）
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chapters import collection_name, safe_dirname, scan_source  # noqa: E402
from manifest import Manifest, STATUS_FAILED, STATUS_OK, file_sha256  # noqa: E402
from markdown_utils import fmt_timestamp  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

NOTE_TEMPLATE = """# {chapter} · 阅读笔记

> 本文件用于个人批注。转换工具只在文件不存在时创建，不会覆盖你的内容。

## 我的批注



## 疑问



## 相关链接

- [正文](正文.md)
- [音频转写](音频转写.md)
"""


def setup_proxy_from_system():
    """若未显式设置代理且 macOS 系统代理启用，则沿用系统代理（用于下载模型）。"""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return
    try:
        out = subprocess.run(["scutil", "--proxy"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return
    if "HTTPSEnable : 1" in out:
        host = port = None
        for line in out.splitlines():
            if "HTTPSProxy :" in line:
                host = line.split(":", 1)[1].strip()
            elif "HTTPSPort :" in line:
                port = line.split(":", 1)[1].strip()
        if host and port:
            os.environ["HTTPS_PROXY"] = f"http://{host}:{port}"
            os.environ["HTTP_PROXY"] = f"http://{host}:{port}"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("convert")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(LOG_DIR / "convert.log", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.handlers = [fh, ch]
    return logger


def render_pdf_md(chapter: str, src: Path, result, digest: str) -> str:
    meta = (
        f"<!-- 来源: {src.name} | sha256: {digest[:12]} | 页数: {result.page_count}"
        f" | 扫描版: {'是' if result.is_scanned else '否'} -->\n\n"
    )
    return meta + result.markdown


def render_audio_md(chapter: str, src: Path, result, digest: str) -> str:
    meta = (
        f"# {chapter}（音频转写）\n\n"
        f"> 来源音频：`{src.name}` ｜ 时长: {fmt_timestamp(result.duration)} ｜ "
        f"模型: `{result.model}` ｜ 逐字转写，未做总结或改写。\n\n---\n\n"
    )
    return meta + result.markdown


def process_collection(source: Path, out_root: Path, manifest: Manifest, args,
                       logger: logging.Logger) -> dict:
    coll = collection_name(source.name)
    coll_dir = out_root / safe_dirname(coll)
    coll_dir.mkdir(parents=True, exist_ok=True)
    chapters = scan_source(source)
    logger.info("资料《%s》: 发现 %d 个章节 (%s)", coll, len(chapters), source)

    stats = {"chapters": 0, "pdf_ok": 0, "audio_ok": 0, "skipped": 0, "failed": 0}
    index_rows: list[tuple[str, str | None, str | None]] = []

    # 延迟 import，避免仅处理 PDF 时加载 whisper
    pdf_convert = audio_convert = None

    for chapter, files in chapters.items():
        ch_dir = coll_dir / safe_dirname(chapter)
        ch_dir.mkdir(exist_ok=True)
        ch_meta: dict = {
            "collection": coll, "chapter": chapter, "sources": {}, "outputs": {},
            "status": STATUS_OK, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        stats["chapters"] += 1

        # ---- PDF ----
        pdf_out = None
        if "pdf" in files and args.only in (None, "pdf"):
            src = files["pdf"]
            try:
                digest = file_sha256(src)
                ch_meta["sources"]["pdf"] = {
                    "path": str(src), "sha256": digest, "size": src.stat().st_size}
                if not args.force and manifest.is_done(src, digest):
                    logger.info("跳过(未变化): %s", src.name)
                    stats["skipped"] += 1
                else:
                    if pdf_convert is None:
                        import pdf_convert as pdf_convert  # noqa: PLC0415
                    t0 = time.time()
                    res = pdf_convert.convert_pdf(src)
                    pdf_out = ch_dir / "正文.md"
                    pdf_out.write_text(render_pdf_md(chapter, src, res, digest), encoding="utf-8")
                    manifest.mark(src, digest, STATUS_OK, [str(pdf_out)], extra={
                        "pages": res.page_count, "is_scanned": res.is_scanned,
                        "ocr_pages": res.ocr_pages, "image_pages": res.image_pages,
                        "seconds": round(time.time() - t0, 1)})
                    ch_meta["outputs"]["正文.md"] = {
                        "pages": res.page_count, "is_scanned": res.is_scanned,
                        "ocr_pages": res.ocr_pages, "image_pages": res.image_pages,
                        "chars": res.char_count}
                    stats["pdf_ok"] += 1
                    logger.info("PDF 完成: %s (页数 %d, 扫描版=%s, %.1fs)",
                                src.name, res.page_count, res.is_scanned, time.time() - t0)
            except Exception as e:  # noqa: BLE001
                logger.exception("PDF 失败: %s", src)
                manifest.mark(src, locals().get("digest", ""), STATUS_FAILED, error=str(e))
                ch_meta["status"] = STATUS_FAILED
                ch_meta.setdefault("errors", {})["pdf"] = str(e)
                stats["failed"] += 1
        elif "pdf" in files:
            pdf_out = ch_dir / "正文.md" if (ch_dir / "正文.md").exists() else None

        # ---- 音频 ----
        audio_out = None
        if "audio" in files and args.only in (None, "audio"):
            src = files["audio"]
            try:
                digest = file_sha256(src)
                ch_meta["sources"]["audio"] = {
                    "path": str(src), "sha256": digest, "size": src.stat().st_size}
                if not args.force and manifest.is_done(src, digest):
                    logger.info("跳过(未变化): %s", src.name)
                    stats["skipped"] += 1
                else:
                    if audio_convert is None:
                        import audio_convert as audio_convert  # noqa: PLC0415
                    t0 = time.time()
                    res = audio_convert.transcribe_audio(src, model=args.model)
                    audio_out = ch_dir / "音频转写.md"
                    audio_out.write_text(render_audio_md(chapter, src, res, digest), encoding="utf-8")
                    manifest.mark(src, digest, STATUS_OK, [str(audio_out)], extra={
                        "duration": round(res.duration, 1), "segments": res.segment_count,
                        "low_confidence": res.low_confidence, "model": res.model,
                        "seconds": round(time.time() - t0, 1)})
                    ch_meta["outputs"]["音频转写.md"] = {
                        "duration": round(res.duration, 1), "segments": res.segment_count,
                        "low_confidence": res.low_confidence, "model": res.model}
                    stats["audio_ok"] += 1
                    logger.info("音频完成: %s (时长 %.0fs, %d 段, %.1fs)",
                                src.name, res.duration, res.segment_count, time.time() - t0)
            except Exception as e:  # noqa: BLE001
                logger.exception("音频失败: %s", src)
                manifest.mark(src, locals().get("digest", ""), STATUS_FAILED, error=str(e))
                ch_meta["status"] = STATUS_FAILED
                ch_meta.setdefault("errors", {})["audio"] = str(e)
                stats["failed"] += 1
        elif "audio" in files:
            audio_out = ch_dir / "音频转写.md" if (ch_dir / "音频转写.md").exists() else None

        # ---- 阅读笔记（只在不存在时创建，永不覆盖）----
        note = ch_dir / "阅读笔记.md"
        if not note.exists():
            note.write_text(NOTE_TEMPLATE.format(chapter=chapter), encoding="utf-8")

        # ---- 章节 metadata ----
        (ch_dir / "metadata.json").write_text(
            json.dumps(ch_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        index_rows.append((
            chapter,
            "正文.md" if (ch_dir / "正文.md").exists() else None,
            "音频转写.md" if (ch_dir / "音频转写.md").exists() else None,
        ))

    # ---- 资料级索引 ----
    lines = [f"# {coll} · 索引\n",
             f"> 共 {len(index_rows)} 章。生成时间: {time.strftime('%Y-%m-%d %H:%M')}\n",
             "| 章节 | 正文(PDF) | 音频转写 |", "| --- | --- | --- |"]
    for chapter, pdf_link, audio_link in index_rows:
        from urllib.parse import quote
        base = quote(safe_dirname(chapter))
        p = f"[正文]({base}/{pdf_link})" if pdf_link else "—"
        a = f"[转写]({base}/{audio_link})" if audio_link else "—"
        lines.append(f"| {chapter} | {p} | {a} |")
    (coll_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return stats


def main():
    ap = argparse.ArgumentParser(description="中文 PDF + MP3 → Markdown 批量转换")
    ap.add_argument("--source", action="append", help="资料目录，可多次指定")
    ap.add_argument("--output", default=str(PROJECT_ROOT / "output"))
    ap.add_argument("--only", choices=["pdf", "audio"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
    args = ap.parse_args()

    logger = setup_logging()
    setup_proxy_from_system()

    sources = [Path(s).expanduser() for s in (args.source or [])]
    if not sources:
        src_list = PROJECT_ROOT / "scripts" / "sources.txt"
        if src_list.exists():
            sources = [Path(line.strip()).expanduser()
                       for line in src_list.read_text(encoding="utf-8").splitlines()
                       if line.strip() and not line.startswith("#")]
    if not sources:
        ap.error("请用 --source 指定资料目录，或在 scripts/sources.txt 中每行写一个目录")

    out_root = Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(out_root / ".manifest.json")

    if args.retry_failed:
        failed = set(manifest.failed_sources())
        logger.info("重试模式：%d 个失败文件", len(failed))
        args.force = True  # 失败记录需要强制重转，但仅限失败文件（下方过滤）

    total = {"chapters": 0, "pdf_ok": 0, "audio_ok": 0, "skipped": 0, "failed": 0}
    for src_dir in sources:
        if not src_dir.is_dir():
            logger.error("目录不存在: %s", src_dir)
            continue
        stats = process_collection(src_dir, out_root, manifest, args, logger)
        for k in total:
            total[k] += stats[k]
        manifest.save()

    manifest.save()
    logger.info("全部完成: 章节 %d | PDF 成功 %d | 音频成功 %d | 跳过 %d | 失败 %d",
                total["chapters"], total["pdf_ok"], total["audio_ok"],
                total["skipped"], total["failed"])
    if total["failed"]:
        print(f"\n⚠️ 有 {total['failed']} 个文件失败，详见 logs/convert.log 与 output/.manifest.json")
        sys.exit(2)


if __name__ == "__main__":
    main()
