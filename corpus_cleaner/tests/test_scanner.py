"""Tests for corpus_cleaner.scanner — Stage 1 file scanning and metadata extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from corpus_cleaner.config import PipelineConfig
from corpus_cleaner.scanner import (
    FileMeta,
    _compute_length_bracket,
    _compute_net_char_count,
    _compute_table_ratio,
    _extract_first_h1,
    _extract_meta,
    _extract_primary_lang,
    _merge_multi_part,
    _parse_filename,
    scan_files,
)


# ============================================================================
# _parse_filename
# ============================================================================


class TestParseFilename:
    def test_valid_with_part(self) -> None:
        result = _parse_filename("doc_20240101_001_abc12345_part002.md")
        assert result == {
            "prefix": "doc",
            "timestamp": "20240101",
            "seq": "001",
            "hash": "abc12345",
            "part": 2,
            "ext": "md",
        }

    def test_valid_without_part(self) -> None:
        result = _parse_filename("doc_20240101_001_abc12345.md")
        assert result == {
            "prefix": "doc",
            "timestamp": "20240101",
            "seq": "001",
            "hash": "abc12345",
            "part": 0,
            "ext": "md",
        }

    def test_valid_txt_extension(self) -> None:
        result = _parse_filename("doc_20231201_005_deadbeef.txt")
        assert result["ext"] == "txt"
        assert result["part"] == 0

    def test_invalid_no_timestamp(self) -> None:
        assert _parse_filename("just_a_file.md") == {}

    def test_invalid_wrong_format(self) -> None:
        assert _parse_filename("abc-def-123.md") == {}

    def test_complex_prefix_with_underscores(self) -> None:
        result = _parse_filename("some_long_prefix_20240101_001_abc12345.md")
        assert result["prefix"] == "some_long_prefix"
        assert result["timestamp"] == "20240101"

    def test_prefix_contains_part_word(self) -> None:
        result = _parse_filename("some_part_file_20240101_001_abc12345.md")
        assert result["prefix"] == "some_part_file"
        assert result["part"] == 0

    def test_long_timestamp(self) -> None:
        result = _parse_filename("x_20240101120000_1_deadbeef.md")
        assert result["timestamp"] == "20240101120000"

    def test_hash_case_insensitive(self) -> None:
        result = _parse_filename("x_20240101_1_ABCDEF12.md")
        assert result["hash"] == "ABCDEF12"


# ============================================================================
# _compute_net_char_count
# ============================================================================


class TestNetCharCount:
    def test_empty_string(self) -> None:
        assert _compute_net_char_count("") == 0

    def test_plain_text_unchanged(self) -> None:
        text = "Just plain text without any markup."
        assert _compute_net_char_count(text) == len(text)

    def test_headings_stripped(self) -> None:
        text = "# Heading 1\n## Heading 2\nContent here"
        raw = len(text)
        result = _compute_net_char_count(text)
        assert result < raw

    def test_bold_italic_stripped(self) -> None:
        text = "**bold** and *italic* markers removed"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_bullet_list_stripped(self) -> None:
        text = "- item one\n- item two\ncontent"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_numbered_list_stripped(self) -> None:
        text = "1. first\n2. second\ncontent"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_html_tags_stripped(self) -> None:
        text = '<p>Hello</p> <div class="x">World</div>'
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_table_structure_stripped(self) -> None:
        text = "Before <table><tr><td>data</td></tr></table> After"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_images_removed_entirely(self) -> None:
        text = "See ![alt text](http://example.com/img.png) image"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_links_keep_text_drop_url(self) -> None:
        text = "Visit [Google](http://google.com) now"
        result = _compute_net_char_count(text)
        raw = len(text)
        assert result < raw

    def test_code_fence_keeps_content(self) -> None:
        text = '```python\nprint("hello")\n```\nMore text'
        result = _compute_net_char_count(text)
        assert result > 0

    def test_whitespace_collapsed(self) -> None:
        text = "Multiple    spaces   here"
        result = _compute_net_char_count(text)
        assert result < len(text)

    def test_known_output(self) -> None:
        text = "# Title\n\n**Hello** *World*\n\n- item"
        result = _compute_net_char_count(text)
        assert result == len("Title Hello World item")


# ============================================================================
# _compute_length_bracket
# ============================================================================


class TestLengthBracket:
    def test_small(self) -> None:
        assert _compute_length_bracket(100, (20000, 50000)) == "S"

    def test_small_at_boundary(self) -> None:
        assert _compute_length_bracket(20000, (20000, 50000)) == "S"

    def test_medium(self) -> None:
        assert _compute_length_bracket(30000, (20000, 50000)) == "M"

    def test_medium_at_boundary(self) -> None:
        assert _compute_length_bracket(50000, (20000, 50000)) == "M"

    def test_large(self) -> None:
        assert _compute_length_bracket(60000, (20000, 50000)) == "L"

    def test_zero(self) -> None:
        assert _compute_length_bracket(0, (20000, 50000)) == "S"

    def test_custom_thresholds(self) -> None:
        assert _compute_length_bracket(500, (1000, 5000)) == "S"
        assert _compute_length_bracket(3000, (1000, 5000)) == "M"
        assert _compute_length_bracket(6000, (1000, 5000)) == "L"


# ============================================================================
# _compute_table_ratio
# ============================================================================


class TestTableRatio:
    def test_no_table(self) -> None:
        assert _compute_table_ratio("Plain text\nNo table here") == 0.0

    def test_all_table(self) -> None:
        assert _compute_table_ratio("<table>\n<TABLE>\n<table>") == 1.0

    def test_partial_table(self) -> None:
        text = "<table>\nPlain\n<table>\nMore plain"
        assert _compute_table_ratio(text) == 0.5

    def test_empty(self) -> None:
        assert _compute_table_ratio("") == 0.0

    def test_table_within_line(self) -> None:
        text = "text <table> more text"
        assert _compute_table_ratio(text) == 1.0

    def test_only_whitespace_lines(self) -> None:
        assert _compute_table_ratio("   \n\t\n  ") == 0.0


# ============================================================================
# _extract_first_h1
# ============================================================================


class TestFirstH1:
    def test_finds_first_h1(self) -> None:
        text = "Intro\n# Main Title\n## Subtitle\nContent"
        assert _extract_first_h1(text) == "Main Title"

    def test_no_h1(self) -> None:
        text = "Intro\n## Subtitle\nContent"
        assert _extract_first_h1(text) == ""

    def test_empty(self) -> None:
        assert _extract_first_h1("") == ""

    def test_h1_with_trailing_spaces(self) -> None:
        assert _extract_first_h1("#   padded   ") == "padded"

    def test_skips_h2(self) -> None:
        text = "## Not this\n# Yes this"
        assert _extract_first_h1(text) == "Yes this"


# ============================================================================
# _extract_primary_lang
# ============================================================================


class TestPrimaryLang:
    def test_arabic(self) -> None:
        assert _extract_primary_lang("用户回流阿语筛选") == "AR"

    def test_russian(self) -> None:
        assert _extract_primary_lang("用户回流俄语") == "RU"

    def test_french(self) -> None:
        assert _extract_primary_lang("用户回流法语_1246篇") == "FR"

    def test_french_subset(self) -> None:
        assert _extract_primary_lang("用户回流法语_筛选_200篇") == "FR"

    def test_english(self) -> None:
        assert _extract_primary_lang("用户回流EN多格式") == "EN"

    def test_unknown(self) -> None:
        assert _extract_primary_lang("未知文件夹") == "UNKNOWN"


# ============================================================================
# _extract_meta — integration tests using temp files
# ============================================================================


class TestExtractMeta:
    def test_basic_markdown_file(self) -> None:
        config = PipelineConfig(input_path=".")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Hello World\n\nThis is **bold** and *italic* text.\n")
            f.write("- item one\n- item two\n")
            tmp_path = Path(f.name)

        try:
            meta = _extract_meta(tmp_path, "test_folder", "EN", config)
            assert meta.file_id == tmp_path.stem
            assert meta.primary_lang == "EN"
            assert meta.line_count == 5
            assert meta.first_h1 == "Hello World"
            assert meta.raw_char_count > 0
            assert meta.net_char_count > 0
            assert meta.net_char_count < meta.raw_char_count
            assert meta.length_bracket in ("S", "M", "L")
            assert meta.table_ratio == 0.0
            assert meta.contamination_score == 0.0
            assert meta.content is not None
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_bad_file_returns_error_sentinels(self) -> None:
        config = PipelineConfig(input_path=".")
        nonexistent = Path("__nonexistent_file_xyz__.md")
        meta = _extract_meta(nonexistent, "folder", "AR", config)
        assert meta.detected_lang == "error"
        assert meta.line_count == -1
        assert meta.raw_char_count == -1
        assert meta.net_char_count == -1
        assert meta.content is None

    def test_parsed_filename_populates_fields(self) -> None:
        config = PipelineConfig(input_path=".")
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "doc_20240101_001_abc12345.md"
            file_path.write_text("# Parsed\nContent.", encoding="utf-8")
            meta = _extract_meta(file_path, "test", "EN", config)
            assert meta.file_id == "doc_20240101_001"
            assert meta.timestamp == "20240101"
            assert meta.hash == "abc12345"
            assert meta.part == 0

    def test_table_ratio_computed(self) -> None:
        config = PipelineConfig(input_path=".")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("text\n<table>\n<table>\nplain\n")
            tmp_path = Path(f.name)

        try:
            meta = _extract_meta(tmp_path, "test", "EN", config)
            assert meta.table_ratio == 0.5
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_length_bracket_from_config_thresholds(self) -> None:
        config = PipelineConfig(input_path=".", length_thresholds=(10, 100))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("x" * 5)
            tmp_path = Path(f.name)

        try:
            meta = _extract_meta(tmp_path, "test", "EN", config)
            assert meta.length_bracket == "S"
        finally:
            tmp_path.unlink(missing_ok=True)


# ============================================================================
# _merge_multi_part
# ============================================================================


class TestMergeMultiPart:
    def _make_meta(self, file_id: str, hash_val: str, part: int, content: str) -> FileMeta:
        return FileMeta(
            file_id=file_id,
            timestamp="20240101",
            hash=hash_val,
            part=part,
            path=Path(f"/fake/{file_id}.md"),
            source_folder="test",
            primary_lang="EN",
            detected_lang="en",
            line_count=1,
            table_ratio=0.0,
            first_h1="",
            raw_char_count=len(content),
            net_char_count=len(content),
            length_bracket="S",
            content=content,
        )

    def test_single_files_pass_through(self) -> None:
        a = self._make_meta("id1", "hash1", 0, "content a")
        b = self._make_meta("id2", "hash2", 0, "content b")
        result = _merge_multi_part([a, b])
        assert len(result) == 2

    def test_two_parts_merged(self) -> None:
        p1 = self._make_meta("doc_20240101_001", "abc12345", 1, "part one")
        p2 = self._make_meta("doc_20240101_001", "abc12345", 2, "part two")
        result = _merge_multi_part([p1, p2])
        assert len(result) == 1
        merged = result[0]
        assert merged.part == 0
        assert merged.file_id == "doc_20240101_001"
        assert merged.hash == "abc12345"
        assert merged.content == "part one\npart two"

    def test_parts_sorted_by_number(self) -> None:
        p3 = self._make_meta("id", "h", 3, "three")
        p1 = self._make_meta("id", "h", 1, "one")
        p2 = self._make_meta("id", "h", 2, "two")
        result = _merge_multi_part([p3, p1, p2])
        assert len(result) == 1
        assert result[0].content == "one\ntwo\nthree"

    def test_different_hash_not_merged(self) -> None:
        p1 = self._make_meta("doc", "hashA", 1, "a")
        p2 = self._make_meta("doc", "hashB", 1, "b")
        result = _merge_multi_part([p1, p2])
        assert len(result) == 2

    def test_single_part_not_merged(self) -> None:
        p1 = self._make_meta("id", "h", 1, "only")
        result = _merge_multi_part([p1])
        assert len(result) == 1
        assert result[0].content == "only"

    def test_latest_timestamp_used(self) -> None:
        p1 = self._make_meta("id", "h", 1, "a")
        p1.timestamp = "20230101"
        p2 = self._make_meta("id", "h", 2, "b")
        p2.timestamp = "20240101"
        result = _merge_multi_part([p1, p2])
        assert result[0].timestamp == "20240101"


# ============================================================================
# scan_files — integration test with real temp directories
# ============================================================================


class TestScanFiles:
    def test_scans_md_and_txt_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir) / "用户回流EN多格式"
            folder.mkdir()
            (folder / "a.md").write_text("# A\nContent A.", encoding="utf-8")
            (folder / "b.txt").write_text("Plain text.", encoding="utf-8")
            # A subdirectory should also be scanned.
            sub = folder / "sub"
            sub.mkdir()
            (sub / "c.md").write_text("# C\nNested.", encoding="utf-8")

            config = PipelineConfig(input_path=tmpdir)
            results = scan_files(config)
            assert len(results) == 3

    def test_auto_discovers_user_huiliu_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "用户回流阿语筛选").mkdir()
            (Path(tmpdir) / "用户回流俄语").mkdir()
            (Path(tmpdir) / "other_folder").mkdir()

            # Only the first two match "用户回流*"
            config = PipelineConfig(input_path=tmpdir, folders=[])
            results = scan_files(config)
            # No files in them, so 0 results.
            assert len(results) == 0

    def test_explicit_folders_used_when_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "my_folder"
            target.mkdir()
            (target / "x.md").write_text("# X", encoding="utf-8")

            config = PipelineConfig(input_path=tmpdir, folders=["my_folder"])
            results = scan_files(config)
            assert len(results) == 1

    def test_multi_part_files_merged_during_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir) / "用户回流EN多格式"
            folder.mkdir()
            (folder / "doc_20240101_001_abc12345_part001.md").write_text(
                "# Part 1\nFirst.", encoding="utf-8"
            )
            (folder / "doc_20240101_001_abc12345_part002.md").write_text(
                "# Part 2\nSecond.", encoding="utf-8"
            )

            config = PipelineConfig(input_path=tmpdir)
            results = scan_files(config)
            assert len(results) == 1
            merged = results[0]
            assert merged.part == 0
            assert merged.file_id == "doc_20240101_001"
            assert "First" in (merged.content or "")
            assert "Second" in (merged.content or "")

    def test_primary_lang_extracted_from_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir) / "用户回流法语_1246篇"
            folder.mkdir()
            (folder / "a.md").write_text("Bonjour.", encoding="utf-8")

            config = PipelineConfig(input_path=tmpdir)
            results = scan_files(config)
            assert len(results) == 1
            assert results[0].primary_lang == "FR"
