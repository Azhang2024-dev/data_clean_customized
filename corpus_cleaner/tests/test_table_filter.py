"""Tests for corpus_cleaner.table_filter."""

from __future__ import annotations

import pytest

from corpus_cleaner.table_filter import (
    classify_file_status,
    is_bad_file,
    is_empty_file,
    is_table_file,
)

_CONTENT = "This is a sample document with enough text content to pass the image-only check. It contains multiple sentences and paragraphs of prose that represent a typical corpus file."


class TestIsTableFile:
    """Unit tests for is_table_file."""

    def test_returns_false_for_normal_file(self) -> None:
        """Given a file with table_ratio 0.2, is_table_file returns False."""
        meta = {"table_ratio": 0.2}
        assert not is_table_file(meta, _CONTENT)

    def test_returns_true_for_table_heavy_file(self) -> None:
        """Given a file with table_ratio 0.8, is_table_file returns True."""
        meta = {"table_ratio": 0.8}
        assert is_table_file(meta, _CONTENT)

    def test_returns_false_at_exact_threshold(self) -> None:
        """Given table_ratio 0.70 (equal to default threshold),
        is_table_file returns False because comparison is strictly greater."""
        meta = {"table_ratio": 0.70}
        assert not is_table_file(meta, _CONTENT)

    def test_respects_custom_threshold(self) -> None:
        """Given a custom threshold of 0.50, a ratio of 0.55 returns True."""
        meta = {"table_ratio": 0.55}
        assert is_table_file(meta, _CONTENT, threshold=0.50)

    def test_defaults_missing_ratio_to_zero(self) -> None:
        """Given a meta dict without table_ratio, defaults to 0 (not table)."""
        meta: dict = {}
        assert not is_table_file(meta, _CONTENT)


class TestIsEmptyFile:
    """Unit tests for is_empty_file."""

    def test_returns_true_for_zero_lines(self) -> None:
        """Given line_count 0, is_empty_file returns True."""
        meta = {"line_count": 0}
        assert is_empty_file(meta)

    def test_returns_false_for_positive_lines(self) -> None:
        """Given line_count 42, is_empty_file returns False."""
        meta = {"line_count": 42}
        assert not is_empty_file(meta)

    def test_defaults_missing_count_to_zero(self) -> None:
        """Given a meta dict without line_count, defaults to 0 (empty)."""
        meta: dict = {}
        assert is_empty_file(meta)


class TestIsBadFile:
    """Unit tests for is_bad_file."""

    def test_returns_true_for_bad_status(self) -> None:
        """Given status 'bad', is_bad_file returns True."""
        meta = {"status": "bad"}
        assert is_bad_file(meta)

    def test_returns_false_for_ok_status(self) -> None:
        """Given status 'ok', is_bad_file returns False."""
        meta = {"status": "ok"}
        assert not is_bad_file(meta)

    def test_returns_false_when_status_missing(self) -> None:
        """Given a meta dict without status, is_bad_file returns False."""
        meta: dict = {}
        assert not is_bad_file(meta)


class TestClassifyFileStatus:
    """Unit tests for classify_file_status."""

    def test_classifies_normal_file_as_ok(self) -> None:
        """Given a normal file (table_ratio=0.2, line_count=50),
        classify_file_status returns 'ok'."""
        meta = {"table_ratio": 0.2, "line_count": 50}
        assert classify_file_status(meta, _CONTENT) == "ok"

    def test_classifies_table_heavy_as_table(self) -> None:
        """Given table_ratio 0.8 (above threshold), returns 'table'."""
        meta = {"table_ratio": 0.8, "line_count": 100}
        assert classify_file_status(meta, _CONTENT) == "table"

    def test_classifies_borderline_ratio_as_ok(self) -> None:
        """Given table_ratio exactly 0.70, returns 'ok'
        because threshold comparison is strictly greater."""
        meta = {"table_ratio": 0.70, "line_count": 30}
        assert classify_file_status(meta, _CONTENT) == "ok"

    def test_classifies_empty_as_empty(self) -> None:
        """Given line_count 0, returns 'empty'."""
        meta = {"table_ratio": 0, "line_count": 0}
        assert classify_file_status(meta, _CONTENT) == "empty"

    def test_classifies_bad_as_bad(self) -> None:
        """Given status 'bad', returns 'bad'."""
        meta = {"status": "bad", "table_ratio": 0.1, "line_count": 10}
        assert classify_file_status(meta, _CONTENT) == "bad"

    def test_bad_overrides_table(self) -> None:
        """Given status 'bad' AND high table_ratio, 'bad' wins (priority order)."""
        meta = {"status": "bad", "table_ratio": 0.9, "line_count": 100}
        assert classify_file_status(meta, _CONTENT) == "bad"

    def test_empty_overrides_table(self) -> None:
        """Given line_count 0 AND high table_ratio, 'empty' wins (priority order)."""
        meta = {"table_ratio": 0.9, "line_count": 0}
        assert classify_file_status(meta, _CONTENT) == "empty"

    def test_bad_overrides_empty(self) -> None:
        """Given status 'bad' AND line_count 0, 'bad' wins (priority order)."""
        meta = {"status": "bad", "table_ratio": 0, "line_count": 0}
        assert classify_file_status(meta, _CONTENT) == "bad"
