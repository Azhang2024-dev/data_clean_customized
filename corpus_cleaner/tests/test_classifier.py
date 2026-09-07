"""Tests for corpus_cleaner.classifier — heuristic classification rules."""

from __future__ import annotations

import pytest

from corpus_cleaner.classifier import (
    _has_book_structure,
    _has_code_block,
    _has_exam_pattern,
    _has_lecture_features,
    classify_file,
)


# ---------------------------------------------------------------------------
# Helpers to build test content
# ---------------------------------------------------------------------------

def _n_lines(n: int, prefix: str = "Line") -> str:
    return "\n".join(f"{prefix} {i}" for i in range(n))


def _n_list_lines(n: int) -> str:
    return "\n".join(f"- item {i}" for i in range(n))


# ===========================================================================
# exam — priority 1
# ===========================================================================


class TestClassifyExam:
    def test_returns_exam_when_multiple_choice_dot_pattern(self) -> None:
        content = "Q1\nA. option1\nB. option2\nC. option3\nD. option4\nQ2\nA. x\nB. y\nC. z\nD. w"
        assert classify_file({"line_count": 50}, content) == "exam"

    def test_returns_exam_when_multiple_choice_paren_pattern(self) -> None:
        content = "A) first\nB) second\nC) third\nD) fourth\nA) fifth\nB) sixth"
        assert classify_file({"line_count": 30}, content) == "exam"

    def test_returns_exam_when_checkbox_pattern(self) -> None:
        content = "☐ task one\n☐ task two\n☐ task three\n☐ task four\n☐ task five"
        assert classify_file({"line_count": 10}, content) == "exam"

    def test_returns_exam_when_mixed_markers_reach_threshold(self) -> None:
        content = "A. one\nB. two\nC. three\n☐ four\n☐ five"
        assert classify_file({"line_count": 10}, content) == "exam"

    def test_exam_wins_over_tutorial(self) -> None:
        content = "A. one\nB. two\nC. three\nD. four\nA. five\n```\nprint('hi')\n```"
        assert classify_file({"line_count": 20}, content) == "exam"


# ===========================================================================
# tutorial — priority 2
# ===========================================================================


class TestClassifyTutorial:
    def test_returns_tutorial_when_code_block_present(self) -> None:
        content = "# Tutorial\n\n```python\ndef hello():\n    print('hi')\n```"
        assert classify_file({"line_count": 20}, content) == "tutorial"

    def test_returns_tutorial_with_language_specifier(self) -> None:
        content = "Some text\n\n```javascript\nconst x = 1;\n```"
        assert classify_file({"line_count": 15}, content) == "tutorial"

    def test_returns_tutorial_with_multiple_code_blocks(self) -> None:
        content = "```\nblock1\n```\n\ntext\n\n```\nblock2\n```"
        assert classify_file({"line_count": 20}, content) == "tutorial"

    def test_tutorial_wins_over_book(self) -> None:
        lines = ["# Heading 1", "## Heading 2", "### Heading 3", "```\ncode\n```"]
        padding = _n_lines(500, "pad")
        content = "\n".join(lines) + "\n" + padding
        assert classify_file({"line_count": 504}, content) == "tutorial"


# ===========================================================================
# book — priority 3
# ===========================================================================


class TestClassifyBook:
    def test_returns_book_with_all_three_heading_levels_and_enough_lines(self) -> None:
        header_block = "# H1\n\n## H2\n\n### H3"
        padding = _n_lines(500, "content")
        content = header_block + "\n" + padding
        assert classify_file({"line_count": 504}, content) == "book"

    def test_returns_book_at_exact_threshold(self) -> None:
        header_block = "# Title\n\n## Section\n\n### Subsection"
        padding = _n_lines(500, "x")
        content = header_block + "\n" + padding
        assert classify_file({"line_count": 503}, content) == "book"

    def test_book_not_matched_when_too_few_lines(self) -> None:
        content = "# H1\n\n## H2\n\n### H3\n\nsome text"
        assert classify_file({"line_count": 10}, content) == "short"

    def test_returns_misc_when_missing_heading_level(self) -> None:
        content = "# H1\n\n## H2\n\n" + _n_lines(500, "pad")
        assert classify_file({"line_count": 502}, content) == "misc"


# ===========================================================================
# lecture — priority 4
# ===========================================================================


class TestClassifyLecture:
    def test_returns_lecture_when_keyword_present(self) -> None:
        content = "# lecture notes\n\n" + _n_lines(150, "content")
        assert classify_file({"line_count": 151}, content) == "lecture"

    def test_returns_lecture_when_arabic_keyword_present(self) -> None:
        content = "# سكشن ١\n\n" + _n_lines(200, "محاضرة")
        assert classify_file({"line_count": 201}, content) == "lecture"

    def test_returns_lecture_with_dense_bullet_lists(self) -> None:
        bullets = _n_list_lines(30)
        padding = _n_lines(70, "text")
        content = bullets + "\n" + padding
        assert classify_file({"line_count": 100}, content) == "lecture"

    def test_lecture_not_matched_when_too_few_lines(self) -> None:
        content = "lecture intro\n" + _n_lines(50, "text")
        assert classify_file({"line_count": 51}, content) == "short"

    def test_lecture_not_matched_when_too_many_lines(self) -> None:
        content = "# محاضرة\n\n" + _n_lines(600, "text")
        assert classify_file({"line_count": 601}, content) == "misc"


# ===========================================================================
# short — priority 5
# ===========================================================================


class TestClassifyShort:
    def test_returns_short_when_few_lines_and_no_other_pattern(self) -> None:
        content = "A short note about something."
        assert classify_file({"line_count": 5}, content) == "short"

    def test_returns_short_at_upper_bound(self) -> None:
        content = _n_lines(99, "line")
        assert classify_file({"line_count": 99}, content) == "short"

    def test_returns_short_for_single_line(self) -> None:
        content = "Just one line."
        assert classify_file({"line_count": 1}, content) == "short"


# ===========================================================================
# misc — priority 7
# ===========================================================================


class TestClassifyMisc:
    def test_returns_misc_for_medium_content_no_patterns(self) -> None:
        content = _n_lines(200, "paragraph")
        assert classify_file({"line_count": 200}, content) == "misc"

    def test_returns_misc_for_empty_content_with_sufficient_lines(self) -> None:
        content = _n_lines(150, "")
        assert classify_file({"line_count": 150}, content) == "misc"

    def test_returns_short_when_heading_levels_present_but_too_few_lines(self) -> None:
        content = "# H1\n\n## H2\n\n### H3\n\ntext"
        assert classify_file({"line_count": 5}, content) == "short"

    def test_returns_misc_for_large_content_no_headings(self) -> None:
        content = _n_lines(600, "long content without any structure")
        assert classify_file({"line_count": 600}, content) == "misc"


# ===========================================================================
# table — priority 6 (Stage 2 fallback)
# ===========================================================================


class TestClassifyTable:
    def test_returns_table_when_ratio_exceeds_threshold(self) -> None:
        content = _n_lines(200, "text")
        assert classify_file({"line_count": 200, "table_ratio": 0.85}, content) == "table"

    def test_returns_misc_when_table_ratio_below_threshold(self) -> None:
        content = _n_lines(200, "text")
        assert classify_file({"line_count": 200, "table_ratio": 0.50}, content) == "misc"


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestHasExamPattern:
    def test_returns_false_when_below_threshold(self) -> None:
        assert _has_exam_pattern("A. one\nB. two") is False

    def test_returns_true_with_exact_threshold(self) -> None:
        assert _has_exam_pattern("A. a\nB. b\nC. c\nD. d\nA) e") is True

    def test_returns_false_for_empty_content(self) -> None:
        assert _has_exam_pattern("") is False


class TestHasCodeBlock:
    def test_returns_true_with_triple_backtick(self) -> None:
        assert _has_code_block("```\ncode\n```") is True

    def test_returns_false_without_backtick(self) -> None:
        assert _has_code_block("plain text") is False

    def test_returns_false_with_single_backtick(self) -> None:
        assert _has_code_block("`inline code`") is False


class TestHasBookStructure:
    def test_returns_true_with_all_three_levels_and_enough_lines(self) -> None:
        content = "# A\n## B\n### C"
        assert _has_book_structure(content, 501) is True

    def test_returns_false_when_line_count_at_threshold(self) -> None:
        content = "# A\n## B\n### C"
        assert _has_book_structure(content, 500) is False

    def test_returns_false_when_missing_h2(self) -> None:
        content = "# A\n### C"
        assert _has_book_structure(content, 501) is False


class TestHasLectureFeatures:
    def test_returns_true_with_keyword_in_range(self) -> None:
        content = "# lecture 1\n" + _n_lines(150, "text")
        assert _has_lecture_features(content, 151) is True

    def test_returns_false_when_below_min_lines(self) -> None:
        content = "lecture intro"
        assert _has_lecture_features(content, 5) is False

    def test_returns_true_with_dense_lists(self) -> None:
        bullets = _n_list_lines(20)
        padding = _n_lines(80, "text")
        content = bullets + "\n" + padding
        assert _has_lecture_features(content, 100) is True

    def test_returns_false_with_sparse_lists(self) -> None:
        content = "- item1\n" + _n_lines(200, "text")
        assert _has_lecture_features(content, 201) is False
