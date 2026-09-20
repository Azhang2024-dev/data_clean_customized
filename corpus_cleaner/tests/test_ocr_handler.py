"""Tests for corpus_cleaner.ocr_handler — contamination detection (Stage 3)."""

from __future__ import annotations

import pytest

from corpus_cleaner.ocr_handler import (
    _is_contaminant_char,
    _is_independent_span,
    _lang_allows_cjk,
    _mark_code_blocks,
    _strip_whitelist,
    clean_content,
    compute_contamination,
)


# ══════════════════════════════════════════════════════════════════════════════
# _is_contaminant_char
# ══════════════════════════════════════════════════════════════════════════════


class TestIsContaminantChar:
    """Unit tests for _is_contaminant_char — single-character CJK detection."""

    @pytest.mark.parametrize(
        "char,primary_lang",
        [
            ("\u6f22", "AR"),  # 漢 — CJK
            ("\u6f22", "RU"),
            ("\u6f22", "FR"),
            ("\u6f22", "EN"),
            ("\u5b57", "AR"),  # 字 — CJK
            ("\u4e2d", "RU"),  # 中 — CJK
            ("\u6f22", "ID"),
        ],
    )
    def test_cjk_char_flagged_for_non_cjk_languages(
        self, char: str, primary_lang: str
    ) -> None:
        """Given a CJK character, _is_contaminant_char returns True
        for non-CJK primary languages (AR/RU/FR/EN/ID)."""
        assert _is_contaminant_char(char, primary_lang) is True

    @pytest.mark.parametrize(
        "char,primary_lang",
        [
            ("\u6f22", "ZH"),
            ("\u4e2d", "zh"),
            ("\u5b57", "ZH-CN"),
            ("\u6f22", "EN+ZH"),  # bilingual allowlist includes zh
            ("\u6f22", "JA"),
            ("\u6f22", "KO"),
        ],
    )
    def test_cjk_char_not_contaminant_for_cjk_native_langs(
        self, char: str, primary_lang: str
    ) -> None:
        """Han is native for zh/ja/ko (and bilingual allowlists with zh)."""
        assert _lang_allows_cjk(primary_lang) is True
        assert _is_contaminant_char(char, primary_lang) is False

    def test_zh_content_contamination_score_near_zero(self) -> None:
        """Pure Chinese text under primary_lang=ZH must not be flagged contaminated."""
        content = "这是一段中文内容，用于验证汉字不被当作污染。\n第二行同样是汉字。"
        score, details = compute_contamination(content, "ZH")
        assert score == 0.0
        assert all(d["contaminant_chars"] == 0 for d in details)

    @pytest.mark.parametrize(
        "char,primary_lang",
        [
            ("a", "AR"),
            ("Z", "RU"),
            ("\u0633", "AR"),  # س — Arabic
            ("\u043f", "RU"),  # п — Cyrillic
            ("\u00e9", "FR"),  # é — French accented
            ("e", "EN"),
        ],
    )
    def test_non_cjk_char_not_flagged(
        self, char: str, primary_lang: str
    ) -> None:
        """Given a non-CJK character (Latin, Arabic, Cyrillic, French accented),
        _is_contaminant_char returns False — contextual checks are handled
        at the line level."""
        assert _is_contaminant_char(char, primary_lang) is False


# ══════════════════════════════════════════════════════════════════════════════
# _mark_code_blocks
# ══════════════════════════════════════════════════════════════════════════════


class TestMarkCodeBlocks:
    """Unit tests for _mark_code_blocks."""

    def test_single_code_block(self) -> None:
        """Given text with one fenced code block, return line indices
        inside and including the fences."""
        text = "line0\n```\ncode1\ncode2\n```\nline5"
        result = _mark_code_blocks(text)
        assert result == {1, 2, 3, 4}

    def test_multiple_code_blocks(self) -> None:
        """Given text with two separate code blocks, return indices
        for both."""
        text = "a\n```\nb\n```\nc\n```\nd\n```\ne"
        result = _mark_code_blocks(text)
        assert result == {1, 2, 3, 5, 6, 7}

    def test_no_code_blocks(self) -> None:
        """Given text without code fences, return empty set."""
        text = "line1\nline2\nline3"
        result = _mark_code_blocks(text)
        assert result == set()

    def test_unclosed_code_block(self) -> None:
        """Given an unclosed code block, mark from the opening fence
        to end of file."""
        text = "before\n```\ninside1\ninside2"
        result = _mark_code_blocks(text)
        assert result == {1, 2, 3}


# ══════════════════════════════════════════════════════════════════════════════
# _strip_whitelist
# ══════════════════════════════════════════════════════════════════════════════


class TestStripWhitelist:
    """Unit tests for _strip_whitelist."""

    def test_url_stripped_to_spaces(self) -> None:
        """Given text with a URL, replace the URL with spaces
        preserving string length."""
        text = "visit https://example.com/page now"
        result = _strip_whitelist(text)
        # "https://example.com/page" = 25 chars.
        url_len = len("https://example.com/page")
        expected = f"visit {' ' * url_len} now"
        assert result == expected
        assert len(result) == len(text)

    def test_email_stripped(self) -> None:
        """Given text with an email address, replace it with spaces."""
        text = "contact user@example.com for help"
        result = _strip_whitelist(text)
        assert "user@example.com" not in result
        assert len(result) == len(text)

    def test_abbreviation_stripped(self) -> None:
        """Given text with an uppercase abbreviation, replace it."""
        text = "read the PDF document"
        result = _strip_whitelist(text)
        assert "PDF" not in result
        assert len(result) == len(text)

    def test_multiple_whitelist_items(self) -> None:
        """Given text with URL + email + abbreviation, all are stripped."""
        text = "see https://a.b or email x@y.z or API key"
        result = _strip_whitelist(text)
        assert "https://a.b" not in result
        assert "x@y.z" not in result
        assert "API" not in result
        assert len(result) == len(text)


# ══════════════════════════════════════════════════════════════════════════════
# compute_contamination
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeContamination:
    """Unit / integration tests for compute_contamination."""

    # ── clean content ──────────────────────────────────────────────────────

    def test_clean_arabic_returns_near_zero(self) -> None:
        """Given pure Arabic text without contamination,
        the score is 0.0."""
        content = "\u0633\u0644\u0627\u0645\n\u0639\u0627\u0644\u0645"
        score, details = compute_contamination(content, "AR")
        assert score == 0.0
        assert len(details) == 2

    def test_clean_english_returns_zero(self) -> None:
        """Given pure English text, the score is 0.0."""
        content = "hello world\nthis is a test\nno contamination here"
        score, details = compute_contamination(content, "EN")
        assert score == 0.0
        assert all(d["contaminant_chars"] == 0 for d in details)

    # ── CJK contamination ──────────────────────────────────────────────────

    def test_arabic_with_cjk_contamination(self) -> None:
        """Given Arabic text with CJK characters, the score reflects
        the contaminated fraction."""
        # 4 Arabic chars + 1 CJK = 5 total, 1 contaminant → 0.2 per line
        content = "\u0633\u0644\u0627\u0645\u6f22"
        score, details = compute_contamination(content, "AR")
        assert len(details) == 1
        assert details[0]["fraction"] == pytest.approx(0.2)
        assert score == pytest.approx(0.2)

    def test_english_with_cjk_contamination(self) -> None:
        """Given English text with CJK characters, the score > 0."""
        content = "hello\u6f22 world\u5b57"
        score, details = compute_contamination(content, "EN")
        assert len(details) == 1
        assert details[0]["contaminant_chars"] == 2
        assert details[0]["fraction"] == pytest.approx(2 / 13)

    # ── embedded Latin ─────────────────────────────────────────────────────

    def test_arabic_embedded_latin_detected(self) -> None:
        """Given Arabic text with Latin letters between Arabic chars,
        those Latin letters are flagged as contaminants."""
        content = "\u0633ab\u0627"
        score, details = compute_contamination(content, "AR")
        assert details[0]["fraction"] == pytest.approx(2 / 4)
        assert score == pytest.approx(2 / 4)

    def test_russian_embedded_latin_detected(self) -> None:
        """Given Russian text with Latin letters between Cyrillic chars,
        those Latin letters are flagged."""
        # п (Cyrillic) + xy (Latin) + р (Cyrillic) = "пxyр"
        content = "\u043fxy\u0440"
        score, details = compute_contamination(content, "RU")
        # stripped = "пxyр" (4 chars), 2 contaminant → 0.5
        assert details[0]["fraction"] == pytest.approx(2 / 4)
        assert score == pytest.approx(2 / 4)

    def test_arabic_latin_not_embedded_not_flagged(self) -> None:
        """Given Latin letters in Arabic text that are NOT between
        Arabic chars (standalone), they are NOT flagged as contaminants."""
        # "hello س" — Latin standalone, no Arabic on both sides
        content = "hello \u0633\u0644\u0627\u0645"
        score, _details = compute_contamination(content, "AR")
        # Only the Arabic chars remain; Latin "hello" is not embedded.
        # After whitelist strip: "hello سلام" → "       سلام"
        # Wait, "hello" is not in the whitelist, so it stays.
        # "hello سلام" has 5 Latin + 1 space + 4 Arabic = 10 chars.
        # CJK: none. Embedded Latin: no match (no Arabic-Latin-Arabic pattern).
        # So contaminant = 0, score = 0.
        assert score == 0.0

    # ── garbled sequences (FR) ─────────────────────────────────────────────

    def test_french_garbled_sequence_detected(self) -> None:
        """Given French text with ≥3 consecutive non-alnum symbols,
        those symbols are flagged."""
        content = "Bonjour!!! monde"
        score, details = compute_contamination(content, "FR")
        # stripped = "Bonjour!!! monde" (16 chars)
        # CJK: 0. Garbled: "!!!" at positions 7,8,9 → 3 contaminants.
        # fraction = 3/16
        assert details[0]["fraction"] == pytest.approx(3 / 16)

    def test_french_two_symbols_not_flagged(self) -> None:
        """Given French text with only 2 consecutive non-alnum symbols,
        they are NOT flagged (threshold is ≥3)."""
        content = "Bonjour!! monde"
        score, _details = compute_contamination(content, "FR")
        assert score == 0.0

    # ── whitelist exemption ────────────────────────────────────────────────

    def test_whitelist_url_exempt_from_contamination(self) -> None:
        """Given Arabic text containing a URL, the URL is stripped
        before contamination analysis and does not contribute to the score."""
        # URL contains Latin chars, but they're whitelisted.
        content = "\u0633\u0644\u0627\u0645 https://example.com \u0639\u0627\u0644\u0645"
        score, details = compute_contamination(content, "AR")
        # After whitelist strip: "سلام                        عالم"
        # The URL (22 chars) → 22 spaces.
        # No CJK, no embedded Latin (Latin in URL is stripped).
        assert score == 0.0

    def test_whitelist_email_and_abbrev_exempt(self) -> None:
        """Given Russian text with email and abbreviation, those
        Latin tokens are exempt."""
        content = "\u043f\u0440\u0438\u0432\u0435\u0442 user@mail.ru PDF"
        score, _details = compute_contamination(content, "RU")
        # Email and "PDF" are whitelisted → stripped.
        assert score == 0.0

    # ── code-block exemption ───────────────────────────────────────────────

    def test_code_block_lines_exempt(self) -> None:
        """Given Arabic text where contamination only appears inside
        code blocks, the score is 0.0."""
        content = (
            "\u0633\u0644\u0627\u0645\n"
            "```\n"
            "\u6f22\u5b57\n"  # CJK inside code block → exempt
            "```\n"
            "\u0639\u0627\u0644\u0645"
        )
        score, details = compute_contamination(content, "AR")
        # Only lines 0 and 4 are analyzed (both clean Arabic).
        assert score == 0.0
        # Detail list should have 2 entries (lines 0 and 4).
        assert len(details) == 2

    # ── 95th-percentile aggregation ────────────────────────────────────────

    def test_95th_percentile_robust_to_outliers(self) -> None:
        """Given 20 clean lines and 1 heavily contaminated line,
        the 95th-percentile score ignores the single outlier."""
        # 20 clean lines + 1 contaminated line
        lines = ["hello"] * 20 + ["\u6f22\u5b57\u4e2d"]
        content = "\n".join(lines)
        score, details = compute_contamination(content, "EN")
        # 21 lines: 20 with fraction 0, 1 with fraction 1.0.
        # 95th percentile of 21 sorted values:
        # sorted = [0,0,...,0,1.0] (20 zeros, 1 one)
        # index = max(0, int(0.95 * 21) - 1) = max(0, 19 - 1) = 18
        # sorted[18] = 0
        assert score == 0.0

    # ── empty / edge cases ─────────────────────────────────────────────────

    def test_empty_content_returns_zero(self) -> None:
        """Given empty content, the score is 0.0 with empty detail list."""
        score, details = compute_contamination("", "AR")
        assert score == 0.0
        assert details == []

    def test_whitespace_only_content(self) -> None:
        """Given whitespace-only content, the score is 0.0."""
        score, details = compute_contamination("   \n  \n   ", "EN")
        assert score == 0.0
        assert details == []

    def test_detail_above_threshold_flag(self) -> None:
        """Given a custom threshold, the above_threshold field
        correctly flags contaminated lines."""
        content = "clean\n\u6f22\u5b57\nmore clean"
        _score, details = compute_contamination(content, "EN", threshold=0.3)
        # Line 0: "clean" → fraction 0.0 → not above
        # Line 1: "漢字" → fraction 1.0 → above (1.0 > 0.3)
        # Line 2: "more clean" → fraction 0.0 → not above
        assert details[0]["above_threshold"] is False
        assert details[1]["above_threshold"] is True
        assert details[2]["above_threshold"] is False

    def test_primary_lang_case_sensitive(self) -> None:
        """Given primary_lang 'ar' (lowercase), it should NOT match
        the AR rules because the check is exact string comparison."""
        # This tests that we don't accidentally normalize case.
        content = "\u0633ab\u0627"
        score, _details = compute_contamination(content, "ar")
        # "ar" != "AR" → embedded Latin regex not applied.
        # CJK check: 0 CJK chars. Score = 0.
        assert score == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# _is_independent_span
# ══════════════════════════════════════════════════════════════════════════════


class TestIsIndependentSpan:
    """Unit tests for _is_independent_span."""

    def test_independent_surrounded_by_spaces(self) -> None:
        """Given a span surrounded by spaces on both sides,
        it is independent."""
        assert _is_independent_span("hello \u6f22\u5b57 world", 6, 8) is True

    def test_independent_at_start_of_string(self) -> None:
        """Given a span at the start of the string,
        it is independent (left side is boundary)."""
        assert _is_independent_span("\u6f22\u5b57 hello", 0, 2) is True

    def test_independent_at_end_of_string(self) -> None:
        """Given a span at the end of the string,
        it is independent (right side is boundary)."""
        assert _is_independent_span("hello \u6f22\u5b57", 6, 8) is True

    def test_embedded_adjacent_to_word_char(self) -> None:
        """Given a span adjacent to a word character on one side,
        it is embedded."""
        # "abc漢字" — CJK adjacent to Latin word chars
        assert _is_independent_span("abc\u6f22\u5b57", 3, 5) is False

    def test_embedded_surrounded_by_word_chars(self) -> None:
        """Given a span surrounded by word characters on both sides,
        it is embedded."""
        assert _is_independent_span("a\u6f22b", 1, 2) is False

    def test_independent_surrounded_by_punctuation(self) -> None:
        """Given a span surrounded by punctuation marks,
        it is independent."""
        assert _is_independent_span("(\u6f22\u5b57),", 1, 3) is True


# ══════════════════════════════════════════════════════════════════════════════
# clean_content
# ══════════════════════════════════════════════════════════════════════════════


class TestCleanContent:
    """Unit / integration tests for clean_content — all four modes."""

    # ── flag-only ───────────────────────────────────────────────────────────

    def test_flag_only_returns_content_unchanged(self) -> None:
        """Given flag-only mode, content is returned unchanged
        with an empty changes list."""
        content = "hello \u6f22\u5b57 world"
        result, changes = clean_content(content, "EN", "flag-only")
        assert result == content
        assert changes == []

    # ── clean-mark ──────────────────────────────────────────────────────────

    def test_clean_mark_replaces_cjk_with_placeholder(self) -> None:
        """Given clean-mark mode with CJK contamination,
        each contaminant span is replaced with [?]."""
        content = "hello \u6f22\u5b57 world"
        result, changes = clean_content(content, "EN", "clean-mark")
        assert result == "hello [?] world"
        assert len(changes) == 1
        assert changes[0]["original"] == "\u6f22\u5b57"
        assert changes[0]["replacement"] == "[?]"
        assert changes[0]["mode"] == "clean-mark"

    def test_clean_mark_groups_consecutive_contaminants(self) -> None:
        """Given clean-mark mode with consecutive CJK chars,
        they are grouped into a single [?]."""
        content = "text \u6f22\u5b57\u4e2d more"
        result, changes = clean_content(content, "EN", "clean-mark")
        assert result == "text [?] more"
        assert len(changes) == 1
        assert changes[0]["original"] == "\u6f22\u5b57\u4e2d"

    def test_clean_mark_multiple_separate_contaminants(self) -> None:
        """Given clean-mark mode with two separate contaminant spans,
        each gets its own [?]."""
        content = "a \u6f22 b \u5b57 c"
        result, changes = clean_content(content, "EN", "clean-mark")
        assert result == "a [?] b [?] c"
        assert len(changes) == 2

    def test_clean_mark_embedded_latin_arabic(self) -> None:
        """Given clean-mark mode with embedded Latin in Arabic text,
        the Latin chars are replaced with [?]."""
        content = "\u0633ab\u0627"
        result, changes = clean_content(content, "AR", "clean-mark")
        assert result == "\u0633[?]\u0627"
        assert len(changes) == 1
        assert changes[0]["original"] == "ab"

    def test_clean_mark_preserves_syntax_structure(self) -> None:
        """Given clean-mark mode, Arabic conjunction + contaminant
        preserves the conjunction (not dangling)."""
        content = "\u0648\u6f22"  # و + CJK
        result, changes = clean_content(content, "AR", "clean-mark")
        assert result == "\u0648[?]"
        assert len(changes) == 1

    # ── clean-light ─────────────────────────────────────────────────────────

    def test_clean_light_deletes_independent_cjk(self) -> None:
        """Given clean-light mode with CJK surrounded by spaces,
        the contaminant is deleted."""
        content = "\u0627\u0644\u0628\u0631\u0645\u062c\u064a\u0627\u062a \u6f22\u5b57 \u062a\u0633\u062a\u062e\u062f\u0645"
        result, changes = clean_content(content, "AR", "clean-light")
        assert result == "\u0627\u0644\u0628\u0631\u0645\u062c\u064a\u0627\u062a  \u062a\u0633\u062a\u062e\u062f\u0645"
        assert len(changes) == 1
        assert changes[0]["replacement"] == ""

    def test_clean_light_marks_embedded_cjk(self) -> None:
        """Given clean-light mode with CJK adjacent to word chars,
        the contaminant is replaced with [?]."""
        content = "abc\u6f22\u5b57def"
        result, changes = clean_content(content, "EN", "clean-light")
        assert result == "abc[?]def"
        assert len(changes) == 1
        assert changes[0]["replacement"] == "[?]"

    def test_clean_light_embedded_latin_in_arabic(self) -> None:
        """Given clean-light mode with embedded Latin between Arabic chars,
        the embedded Latin is marked (not deleted)."""
        content = "\u0633ab\u0627"
        result, changes = clean_content(content, "AR", "clean-light")
        assert result == "\u0633[?]\u0627"
        assert changes[0]["replacement"] == "[?]"

    # ── clean-aggressive ────────────────────────────────────────────────────

    def test_clean_aggressive_deletes_all_contaminants(self) -> None:
        """Given clean-aggressive mode, all contaminant characters
        are deleted."""
        content = "hello \u6f22\u5b57 world \u4e2d"
        result, changes = clean_content(content, "EN", "clean-aggressive")
        assert result == "hello  world "
        # 2 contaminant spans + 1 warning per line
        assert len(changes) == 3
        assert all(c["replacement"] == "" for c in changes if "warning" not in c)

    def test_clean_aggressive_warns_about_semantic_damage(self) -> None:
        """Given clean-aggressive mode, changes list includes a warning
        about potential semantic damage."""
        content = "text \u6f22"
        _result, changes = clean_content(content, "EN", "clean-aggressive")
        warnings = [c for c in changes if "warning" in c]
        assert len(warnings) >= 1
        assert "semantics" in warnings[0]["warning"]

    # ── exemptions ──────────────────────────────────────────────────────────

    def test_code_block_content_exempt_from_cleaning(self) -> None:
        """Given content with contaminants inside code blocks,
        those contaminants are NOT cleaned."""
        content = "before\n```\n\u6f22\u5b57\n```\nafter"
        result, changes = clean_content(content, "EN", "clean-mark")
        assert "\u6f22\u5b57" in result
        assert changes == []

    def test_whitelist_content_exempt_from_cleaning(self) -> None:
        """Given content with whitelist tokens (URLs),
        those tokens are NOT cleaned."""
        content = "\u0633\u0644\u0627\u0645 https://example.com \u6f22"
        result, changes = clean_content(content, "AR", "clean-mark")
        assert "https://example.com" in result
        assert "[?]" in result  # CJK is still cleaned

    def test_multiline_content_cleaning(self) -> None:
        """Given multiline content with contaminants on multiple lines,
        each line is cleaned independently."""
        content = "line1 \u6f22\nline2 \u5b57"
        result, changes = clean_content(content, "EN", "clean-mark")
        assert result == "line1 [?]\nline2 [?]"
        assert len(changes) == 2

    # ── error handling ──────────────────────────────────────────────────────

    def test_invalid_mode_raises_value_error(self) -> None:
        """Given an unknown mode, ValueError is raised."""
        with pytest.raises(ValueError, match="Unknown mode"):
            clean_content("text", "EN", "invalid-mode")

    def test_empty_content_all_modes(self) -> None:
        """Given empty content, all modes return empty content
        with empty changes list."""
        for mode in ("flag-only", "clean-mark", "clean-light", "clean-aggressive"):
            result, changes = clean_content("", "EN", mode)
            assert result == ""
            assert changes == []
