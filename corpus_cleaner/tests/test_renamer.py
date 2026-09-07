"""Tests for corpus_cleaner.renamer."""

from __future__ import annotations

import pytest

from corpus_cleaner.renamer import (
    _compute_length_bracket,
    _extract_title,
    _sanitize,
    generate_new_name,
)


class TestExtractTitle:
    """Unit tests for _extract_title."""

    def test_extracts_h1_heading(self) -> None:
        """Given content with # heading, _extract_title returns the heading text."""
        content = "# Basic Clinical Anesthesia\n\nSome body text here."
        assert _extract_title(content) == "Basic Clinical Anesthesia"

    def test_extracts_h2_heading_when_no_h1(self) -> None:
        """Given content with ## heading but no # heading, returns h2 text."""
        content = "## Introduction to PHP\n\nBody text."
        assert _extract_title(content) == "Introduction to PHP"

    def test_skips_empty_headings(self) -> None:
        """Given # followed by whitespace only, skips to next heading."""
        content = "#   \n# Real Title\n\nBody."
        assert _extract_title(content) == "Real Title"

    def test_returns_h1_before_h2(self) -> None:
        """Given both # and ## headings, returns h1 (higher priority)."""
        content = "## Second\n# First\n\nBody."
        assert _extract_title(content) == "First"

    def test_fallback_to_first_non_html_line(self) -> None:
        """Given no headings, returns first non-empty, non-HTML line in first 20."""
        content = "\n\n<html>\n\nFirst real paragraph here.\n\nMore text."
        assert _extract_title(content) == "First real paragraph here."

    def test_skips_markdown_image_lines(self) -> None:
        """Given ![alt](url) as first non-empty line, skips to next."""
        content = "![diagram](img/diag.png)\n\nActual title text."
        assert _extract_title(content) == "Actual title text."

    def test_returns_untitled_for_empty_content(self) -> None:
        """Given empty content, returns 'untitled'."""
        assert _extract_title("") == "untitled"

    def test_returns_untitled_when_all_html_or_images(self) -> None:
        """Given only HTML/image lines in first 20, returns 'untitled'."""
        content = "<table>\n<tr>\n<td>\n</table>\n![img](x.png)"
        assert _extract_title(content) == "untitled"


class TestSanitize:
    """Unit tests for _sanitize."""

    def test_replaces_windows_forbidden_chars(self) -> None:
        """Given title with \\/:*?\"<>|, replaces each with _."""
        assert _sanitize('test:file*name') == "test_file_name"

    def test_collapses_whitespace_to_underscore(self) -> None:
        """Given title with multiple spaces/newlines, collapses to single _."""
        assert _sanitize("hello   world\ttab") == "hello_world_tab"

    def test_lowercases_latin_only(self) -> None:
        """Given title with Latin letters, lowercases them."""
        assert _sanitize("HELLO World") == "hello_world"

    def test_preserves_arabic_characters(self) -> None:
        """Given Arabic title, preserves characters unchanged (no case concept)."""
        assert _sanitize("محاسبة") == "محاسبة"

    def test_preserves_cyrillic_characters(self) -> None:
        """Given Cyrillic title, preserves characters unchanged (no case concept)."""
        assert _sanitize("Привет мир") == "Привет_мир"

    def test_preserves_cjk_characters(self) -> None:
        """Given CJK title, preserves characters unchanged."""
        assert _sanitize("日本語タイトル") == "日本語タイトル"

    def test_mixed_latin_and_arabic(self) -> None:
        """Given mixed Latin/Arabic, lowercases Latin, preserves Arabic."""
        assert _sanitize("ARABIC محاسبة MIXED") == "arabic_محاسبة_mixed"

    def test_truncates_to_max_topic_chars(self) -> None:
        """Given title longer than _MAX_TOPIC_CHARS, truncates to 50."""
        long_title = "a" * 250
        result = _sanitize(long_title)
        assert len(result) == 50
        assert result == "a" * 50

    def test_truncation_does_not_cut_multibyte_unicode(self) -> None:
        """Given CJK title beyond 50-char boundary, uses Python len() (character count)."""
        title = "日本語" * 80  # 240 CJK chars
        result = _sanitize(title)
        assert len(result) == 50

    def test_strips_leading_trailing_underscores(self) -> None:
        """Given title that becomes _ after sanitize, strips edges."""
        assert _sanitize("???") == "untitled"

    def test_fallback_to_untitled_when_empty_after_sanitize(self) -> None:
        """Given title of only forbidden chars, returns 'untitled'."""
        assert _sanitize('<":|>') == "untitled"


class TestComputeLengthBracket:
    """Unit tests for _compute_length_bracket."""

    def test_returns_s_for_zero(self) -> None:
        """Given net_char_count 0, returns 'S'."""
        assert _compute_length_bracket(0, (20000, 50000)) == "S"

    def test_returns_s_at_sm_boundary(self) -> None:
        """Given net_char_count equal to S/M boundary, returns 'S'."""
        assert _compute_length_bracket(20000, (20000, 50000)) == "S"

    def test_returns_m_above_sm_boundary(self) -> None:
        """Given net_char_count just above S/M boundary, returns 'M'."""
        assert _compute_length_bracket(20001, (20000, 50000)) == "M"

    def test_returns_m_at_ml_boundary(self) -> None:
        """Given net_char_count equal to M/L boundary, returns 'M'."""
        assert _compute_length_bracket(50000, (20000, 50000)) == "M"

    def test_returns_l_above_ml_boundary(self) -> None:
        """Given net_char_count above M/L boundary, returns 'L'."""
        assert _compute_length_bracket(50001, (20000, 50000)) == "L"


class TestGenerateNewName:
    """Unit tests for generate_new_name."""

    H1_CONTENT = "# Basic Clinical Anesthesia\n\nBody text."
    AR_CONTENT = "# محاسبة متقدمة\n\nنص المحتوى."

    def test_generates_name_from_h1_title(self) -> None:
        """Given content with # heading, generates expected filename."""
        meta = {"net_char_count": 60000}
        result = generate_new_name(meta, self.H1_CONTENT, "book", 1)
        assert result == "book_basic_clinical_anesthesia_001_L.md"

    def test_generates_name_with_arabic_title_preserved(self) -> None:
        """Given Arabic content, preserves Arabic in filename."""
        meta = {"net_char_count": 15000}
        result = generate_new_name(meta, self.AR_CONTENT, "short", 2)
        assert result == "short_محاسبة_متقدمة_002_S.md"

    def test_uses_length_bracket_from_meta_when_present(self) -> None:
        """Given meta with length_bracket, uses it instead of computing."""
        meta = {"net_char_count": 999, "length_bracket": "M"}
        result = generate_new_name(meta, "# Title", "lecture", 5)
        assert result == "lecture_title_005_M.md"

    def test_computes_length_bracket_from_net_char_count(self) -> None:
        """Given meta with net_char_count but no length_bracket, computes it."""
        meta = {"net_char_count": 25000}
        result = generate_new_name(meta, "# Title", "book", 10)
        assert result == "book_title_010_M.md"

    def test_zero_pads_seq_to_three_digits(self) -> None:
        """Given seq 7, formats as 007."""
        meta = {"net_char_count": 100}
        result = generate_new_name(meta, "# A", "misc", 7)
        assert result == "misc_a_007_S.md"

    def test_untitled_fallback_in_full_name(self) -> None:
        """Given content with no extractable title, uses 'untitled'."""
        meta = {"net_char_count": 100}
        result = generate_new_name(meta, "<html></html>", "misc", 4)
        assert result == "misc_untitled_004_S.md"

    def test_custom_thresholds_affect_bracket(self) -> None:
        """Given custom thresholds, bracket reflects custom boundaries."""
        meta = {"net_char_count": 8000}
        result = generate_new_name(meta, "# Test", "book", 1, thresholds=(5000, 15000))
        assert result == "book_test_001_M.md"

    def test_missing_net_char_count_defaults_to_zero(self) -> None:
        """Given meta without net_char_count, defaults to 0 → 'S'."""
        meta: dict = {}
        result = generate_new_name(meta, "# Title", "short", 3)
        assert result == "short_title_003_S.md"
