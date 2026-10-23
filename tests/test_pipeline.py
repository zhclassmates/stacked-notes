"""单元测试：章节规范化、目录锚点、增量跳过逻辑。

运行: .venv/bin/python -m pytest tests/ -v
（不依赖原始资料文件，不触网）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from chapters import collection_name, normalize_stem, scan_source  # noqa: E402
from manifest import Manifest, STATUS_OK  # noqa: E402
from markdown_utils import build_toc, fmt_timestamp, github_slug  # noqa: E402


class TestNormalizeStem:
    def test_pdf_mp3_pairing_with_question_mark(self):
        a = normalize_stem("12｜估值：怎样避开资产估值的常见误区.mp3")
        b = normalize_stem("12｜估值：怎样避开资产估值的常见误区？.pdf")
        assert a == b

    def test_watermark_removed(self):
        assert "[" not in normalize_stem("2.10 学习的真相：神经网络[uivita.com].mp3")

    def test_duplicate_suffix_removed(self):
        a = normalize_stem("32｜标的选择3：怎样看懂房子？(1).MP3")
        b = normalize_stem("32｜标的选择3：怎样看懂房子？.mp3")
        assert a == b

    def test_audio_hint_removed(self):
        a = normalize_stem("2.19 学习的真相：必要关联（音频.mp3")
        assert "（音频" not in a

    def test_uppercase_ext(self):
        assert normalize_stem("06｜本质.MP3") == normalize_stem("06｜本质.mp3")


class TestCollectionName:
    def test_strip_number_and_suffix(self):
        assert collection_name("164.吴军·财商训练40讲【完结】") == "吴军·财商训练40讲"

    def test_no_number(self):
        assert collection_name("李笑来·学习的真相·2023【完结】") == "李笑来·学习的真相·2023"


class TestMarkdown:
    def test_slug_chinese(self):
        assert github_slug("财商训练 第一课") == "财商训练-第一课"

    def test_toc_link_valid(self):
        md = "# 标题\n\n## 第一节 概述\n\n内容\n\n## 第二节\n"
        toc = build_toc(md)
        assert "- [第一节 概述](#第一节-概述)" in toc
        assert "- [第二节](#第二节)" in toc

    def test_toc_filters_long_sentence_headings(self):
        md = "# 标题\n\n## 这是一个被误判为标题的非常长的加粗句子，不应该出现在目录里面。\n\n## 课程表\n"
        toc = build_toc(md)
        assert "课程表" in toc
        assert "误判" not in toc

    def test_toc_skips_code_blocks(self):
        md = "# 标题\n\n```\n# 假标题\n```\n\n## 真标题\n"
        toc = build_toc(md)
        assert "假标题" not in toc
        assert "真标题" in toc

    def test_timestamp(self):
        assert fmt_timestamp(0) == "00:00:00"
        assert fmt_timestamp(3661.7) == "01:01:01"


class TestManifest:
    def test_skip_unchanged_and_detect_change(self, tmp_path):
        m = Manifest(tmp_path / ".manifest.json")
        src = tmp_path / "a.pdf"
        src.write_bytes(b"hello")
        from manifest import file_sha256
        d = file_sha256(src)
        assert not m.is_done(src, d)
        m.mark(src, d, STATUS_OK, ["out.md"])
        m.save()
        m2 = Manifest(tmp_path / ".manifest.json")
        assert m2.is_done(src, d)
        # 内容变化后不应跳过
        src.write_bytes(b"changed")
        assert not m2.is_done(src, file_sha256(src))

    def test_corrupt_manifest_recovered(self, tmp_path):
        p = tmp_path / ".manifest.json"
        p.write_text("{broken json", encoding="utf-8")
        m = Manifest(p)  # 不抛异常，重建
        assert m.files == {}


class TestScanSource:
    def test_pairing_and_sorting(self, tmp_path):
        (tmp_path / "02｜B.pdf").write_bytes(b"2")
        (tmp_path / "01｜A.mp3").write_bytes(b"1")
        (tmp_path / "01｜A？.pdf").write_bytes(b"1")
        (tmp_path / "10｜C.mp3").write_bytes(b"1")
        chapters = scan_source(tmp_path)
        keys = list(chapters)
        assert keys == ["01｜A", "02｜B", "10｜C"]
        assert set(chapters["01｜A"]) == {"pdf", "audio"}
        assert set(chapters["02｜B"]) == {"pdf"}

    def test_duplicate_audio_keeps_larger(self, tmp_path):
        (tmp_path / "32｜X.mp3").write_bytes(b"small")
        (tmp_path / "32｜X(1).MP3").write_bytes(b"much larger file")
        chapters = scan_source(tmp_path)
        assert chapters["32｜X"]["audio"].name == "32｜X(1).MP3"
