"""Markdown 工具：GitHub 风格中文锚点、目录生成。"""
from __future__ import annotations

import re


def github_slug(text: str) -> str:
    """生成与 GitHub 一致的标题锚点。

    规则：转小写、去掉标点（保留中日韩字符/字母/数字/空格/连字符）、空格转 -。
    """
    text = text.strip().lower()
    # 去掉 emoji 和标点，保留 \w（含中文）与空格、连字符
    text = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def extract_headings(md_text: str, max_level: int = 3) -> list[tuple[int, str]]:
    """提取 Markdown 标题 [(level, text)]，跳过代码块内的 #。"""
    headings: list[tuple[int, str]] = []
    in_code = False
    for line in md_text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m and len(m.group(1)) <= max_level:
            headings.append((len(m.group(1)), m.group(2)))
    return headings


def _clean_heading_text(text: str) -> str:
    """去掉标题中的加粗/斜体/行内代码标记，用于目录展示与锚点。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


# 目录中允许的最长标题（超出大概率是正文句被误判为标题）
TOC_MAX_HEADING_LEN = 30


def build_toc(md_text: str, max_level: int = 3, skip_first_h1: bool = True) -> str:
    """根据标题生成目录（带内部跳转链接）。

    过滤规则：PDF 提取常把加粗整句误判为标题，目录中剔除
    超长句和以句读标点结尾的"标题"，但正文里的标题本身保留不动。
    """
    headings = extract_headings(md_text, max_level)
    if skip_first_h1 and headings and headings[0][0] == 1:
        headings = headings[1:]
    # 过滤误判标题
    headings = [
        (lv, t) for lv, t in headings
        if len(_clean_heading_text(t)) <= TOC_MAX_HEADING_LEN
        and not _clean_heading_text(t).endswith(("。", "！", "？", ".", "!", "?"))
    ]
    if not headings:
        return ""
    # 以最小层级为基准规整缩进
    min_level = min(lv for lv, _ in headings)
    lines: list[str] = []
    seen: dict[str, int] = {}
    for level, text in headings:
        clean = _clean_heading_text(text)
        slug = github_slug(clean)
        if slug in seen:  # GitHub 对重复标题追加 -1, -2
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        indent = "  " * (level - min_level)
        lines.append(f"{indent}- [{clean}](#{slug})")
    return "\n".join(lines)


def fmt_timestamp(seconds: float) -> str:
    """秒 → HH:MM:SS"""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
