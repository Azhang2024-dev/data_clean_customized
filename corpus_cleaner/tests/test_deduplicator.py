"""Tests for corpus_cleaner.deduplicator."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from corpus_cleaner.deduplicator import (
    DuplicateGroup,
    FileMeta,
    _jaccard_estimate,
    _make_shingles,
    _minhash_signature,
    _shingle_hash,
    _tokenize,
    find_duplicates,
)
from corpus_cleaner.utils import md5_file


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_meta(
    path: Path,
    file_id: str = "",
    hash_from_name: str = "",
    timestamp: float = 0.0,
    primary_lang: str = "EN",
) -> FileMeta:
    """Create a FileMeta with content_md5 computed from the file."""
    return FileMeta(
        path=path,
        file_id=file_id,
        hash_from_name=hash_from_name,
        content_md5=md5_file(path),
        timestamp=timestamp,
        primary_lang=primary_lang,
    )


# ── Unit tests for min-hash helpers ────────────────────────────────────────


class TestTokenize:
    """Tests for _tokenize."""

    def test_splits_and_lowercases(self) -> None:
        result = _tokenize("Hello World FOO")
        assert result == ["hello", "world", "foo"]

    def test_strips_punctuation(self) -> None:
        result = _tokenize("Hello, world! (foo)")
        assert result == ["hello", "world", "foo"]

    def test_handles_empty_string(self) -> None:
        assert _tokenize("") == []

    def test_handles_whitespace_only(self) -> None:
        assert _tokenize("   \t\n  ") == []


class TestMakeShingles:
    """Tests for _make_shingles."""

    def test_3_word_shingles(self) -> None:
        tokens = ["a", "b", "c", "d", "e"]
        result = _make_shingles(tokens, 3)
        assert result == ["a b c", "b c d", "c d e"]

    def test_fewer_tokens_than_k(self) -> None:
        tokens = ["a", "b"]
        result = _make_shingles(tokens, 3)
        assert result == []

    def test_exact_k_tokens(self) -> None:
        tokens = ["a", "b", "c"]
        result = _make_shingles(tokens, 3)
        assert result == ["a b c"]


class TestShingleHash:
    """Tests for _shingle_hash."""

    def test_deterministic(self) -> None:
        h1 = _shingle_hash("hello world foo", 42)
        h2 = _shingle_hash("hello world foo", 42)
        assert h1 == h2

    def test_different_seeds_different_hash(self) -> None:
        h1 = _shingle_hash("hello", 0)
        h2 = _shingle_hash("hello", 1)
        assert h1 != h2

    def test_different_shingles_different_hash(self) -> None:
        h1 = _shingle_hash("a b c", 0)
        h2 = _shingle_hash("x y z", 0)
        assert h1 != h2


class TestMinhashSignature:
    """Tests for _minhash_signature."""

    def test_signature_length(self) -> None:
        tokens = ["a", "b", "c", "d", "e", "f"]
        sig = _minhash_signature(tokens, 128)
        assert len(sig) == 128

    def test_empty_tokens_returns_zeros(self) -> None:
        sig = _minhash_signature([], 128)
        assert sig == [0] * 128

    def test_same_content_same_signature(self) -> None:
        tokens = ["hello", "world", "this", "is", "a", "test"]
        sig1 = _minhash_signature(tokens, 128)
        sig2 = _minhash_signature(tokens, 128)
        assert sig1 == sig2


class TestJaccardEstimate:
    """Tests for _jaccard_estimate."""

    def test_identical_signatures(self) -> None:
        sig = [1, 2, 3, 4, 5]
        assert _jaccard_estimate(sig, sig) == 1.0

    def test_completely_different(self) -> None:
        sig1 = [1, 2, 3, 4, 5]
        sig2 = [6, 7, 8, 9, 10]
        assert _jaccard_estimate(sig1, sig2) == 0.0

    def test_half_match(self) -> None:
        sig1 = [1, 2, 3, 4, 5, 6]
        sig2 = [1, 2, 3, 7, 8, 9]
        assert _jaccard_estimate(sig1, sig2) == 0.5

    def test_empty_signatures(self) -> None:
        assert _jaccard_estimate([], []) == 0.0


# ── Integration tests for find_duplicates ──────────────────────────────────


class TestFindDuplicatesEmpty:
    """Tests for find_duplicates with empty input."""

    def test_empty_list_returns_empty(self) -> None:
        unique, groups = find_duplicates([])
        assert unique == []
        assert groups == []


class TestNoDuplicates:
    """Tests for find_duplicates with all unique files."""

    def test_all_unique(self, tmp_path: Path) -> None:
        # Given: 3 files with different content and different prefixes
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f3 = tmp_path / "c.md"
        f1.write_text("Content alpha one.", encoding="utf-8")
        f2.write_text("Content beta two.", encoding="utf-8")
        f3.write_text("Content gamma three.", encoding="utf-8")

        metas = [
            _make_meta(f1, file_id="id_a", hash_from_name="aaa", timestamp=100.0),
            _make_meta(f2, file_id="id_b", hash_from_name="bbb", timestamp=200.0),
            _make_meta(f3, file_id="id_c", hash_from_name="ccc", timestamp=300.0),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then: all 3 are unique, no duplicate groups
        assert len(unique) == 3
        assert groups == []


class TestExactDuplicates:
    """Tests for find_duplicates with exact content duplicates."""

    def test_two_identical_files_keeps_latest(self, tmp_path: Path) -> None:
        # Given: 2 files with identical content, different timestamps
        content = "The same content in both files.\n" * 10
        f1 = tmp_path / "original.md"
        f2 = tmp_path / "copy.md"
        f1.write_text(content, encoding="utf-8")
        f2.write_text(content, encoding="utf-8")

        metas = [
            _make_meta(f1, file_id="id_01", hash_from_name="h01", timestamp=100.0),
            _make_meta(f2, file_id="id_02", hash_from_name="h02", timestamp=200.0),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then: latest timestamp (f2) is kept, f1 is a duplicate
        assert len(unique) == 1
        assert unique[0].path == f2
        assert len(groups) == 1
        assert groups[0].reason == "exact"
        assert groups[0].similarity == 1.0
        assert groups[0].kept.path == f2
        assert len(groups[0].duplicates) == 1
        assert groups[0].duplicates[0].path == f1

    def test_three_identical_files(self, tmp_path: Path) -> None:
        # Given: 3 files with identical content
        content = "Triple duplicate.\n" * 5
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f3 = tmp_path / "c.md"
        f1.write_text(content, encoding="utf-8")
        f2.write_text(content, encoding="utf-8")
        f3.write_text(content, encoding="utf-8")

        metas = [
            _make_meta(f1, timestamp=100.0),
            _make_meta(f2, timestamp=300.0),
            _make_meta(f3, timestamp=200.0),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then: only latest timestamp is kept
        assert len(unique) == 1
        assert unique[0].path == f2
        assert len(groups) == 1
        assert len(groups[0].duplicates) == 2


class TestSuspectedDuplicates:
    """Tests for find_duplicates with suspected (prefix) duplicates."""

    def test_same_prefix_different_content(self, tmp_path: Path) -> None:
        # Given: 2 files with same file_id+hash_from_name but different content
        f1 = tmp_path / "file_v1.md"
        f2 = tmp_path / "file_v2.md"
        f1.write_text("Version one of the document.\n" * 10, encoding="utf-8")
        f2.write_text("Version two of the document.\n" * 10, encoding="utf-8")

        metas = [
            _make_meta(
                f1, file_id="doc_001", hash_from_name="abc123", timestamp=100.0
            ),
            _make_meta(
                f2, file_id="doc_001", hash_from_name="abc123", timestamp=200.0
            ),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then: both files are kept, but flagged as suspected
        assert len(unique) == 2
        assert len(groups) == 1
        assert groups[0].reason == "suspected"
        assert groups[0].similarity == -1.0
        assert groups[0].kept.timestamp == 200.0  # latest timestamp as reference
        assert len(groups[0].duplicates) == 1

    def test_same_prefix_but_exact_duplicate_handled_first(self, tmp_path: Path) -> None:
        """Given same prefix AND same content, exact dedup fires first.
        Suspected dedup runs on remaining files and finds nothing extra."""
        content = "Same content for both.\n" * 5
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text(content, encoding="utf-8")
        f2.write_text(content, encoding="utf-8")

        metas = [
            _make_meta(
                f1, file_id="doc_001", hash_from_name="abc", timestamp=100.0
            ),
            _make_meta(
                f2, file_id="doc_001", hash_from_name="abc", timestamp=200.0
            ),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then: only exact duplicate group (suspected doesn't fire since MD5s match)
        assert len(unique) == 1
        assert len(groups) == 1
        assert groups[0].reason == "exact"


class TestFuzzyDuplicates:
    """Tests for find_duplicates with fuzzy (semantic) dedup."""

    def test_nearly_identical_files(self, tmp_path: Path) -> None:
        # Given: 2 files with ~500 all-unique words (each word appears once).
        # 500 words → 498 unique 3-word shingles. Changing 1 word affects
        # exactly 3 shingles. Jaccard ≈ 495/501 ≈ 0.988 > 0.95.
        base_words = [f"w{i:04d}" for i in range(500)]
        base_text = " ".join(base_words)
        # Change exactly 1 word (position 250)
        variant_words = list(base_words)
        variant_words[250] = "w9999"
        variant_text = " ".join(variant_words)

        f1 = tmp_path / "base.md"
        f2 = tmp_path / "variant.md"
        f1.write_text(base_text, encoding="utf-8")
        f2.write_text(variant_text, encoding="utf-8")

        metas = [
            _make_meta(f1, timestamp=100.0, primary_lang="EN"),
            _make_meta(f2, timestamp=200.0, primary_lang="EN"),
        ]

        # When
        unique, groups = find_duplicates(metas, fuzzy=True)

        # Then: fuzzy duplicate detected, latest timestamp kept
        assert len(unique) == 1
        assert len(groups) == 1
        assert groups[0].reason == "fuzzy"
        assert groups[0].similarity > 0.95
        assert groups[0].kept.path == f2

    def test_different_languages_not_compared(self, tmp_path: Path) -> None:
        """Given files in different primary_lang groups with similar structure,
        they should NOT be flagged as fuzzy duplicates."""
        text_en = "the cat sat on the mat " * 30
        text_fr = "le chat est assis sur le tapis " * 30
        f1 = tmp_path / "en.md"
        f2 = tmp_path / "fr.md"
        f1.write_text(text_en, encoding="utf-8")
        f2.write_text(text_fr, encoding="utf-8")

        metas = [
            _make_meta(f1, timestamp=100.0, primary_lang="EN"),
            _make_meta(f2, timestamp=200.0, primary_lang="FR"),
        ]

        # When
        unique, groups = find_duplicates(metas, fuzzy=True)

        # Then: no fuzzy duplicates across languages
        assert len(unique) == 2
        assert len(groups) == 0

    def test_dissimilar_files_not_flagged(self, tmp_path: Path) -> None:
        """Given two very different files, fuzzy dedup should not flag them."""
        f1 = tmp_path / "doc_a.md"
        f2 = tmp_path / "doc_b.md"
        f1.write_text(
            "Python is a programming language. It is used for web development, "
            "data science, and machine learning. " * 20,
            encoding="utf-8",
        )
        f2.write_text(
            "Football is a sport played with a ball. Teams compete to score goals. "
            "The World Cup is held every four years. " * 20,
            encoding="utf-8",
        )

        metas = [
            _make_meta(f1, timestamp=100.0, primary_lang="EN"),
            _make_meta(f2, timestamp=200.0, primary_lang="EN"),
        ]

        # When
        unique, groups = find_duplicates(metas, fuzzy=True)

        # Then: no fuzzy duplicates for dissimilar content
        assert len(unique) == 2
        assert len(groups) == 0


class TestMixedScenario:
    """Tests for find_duplicates with a mix of duplicate types."""

    def test_exact_suspected_and_unique(self, tmp_path: Path) -> None:
        # Given: a mix of exact duplicates, suspected duplicates, and unique files
        content_a = "Content alpha unique.\n" * 5
        content_b = "Content beta shared.\n" * 5
        content_c = "Content gamma version 1.\n" * 5
        content_d = "Content gamma version 2.\n" * 5

        f1 = tmp_path / "unique_alpha.md"
        f2 = tmp_path / "beta_original.md"
        f3 = tmp_path / "beta_copy.md"  # exact duplicate of f2
        f4 = tmp_path / "gamma_v1.md"
        f5 = tmp_path / "gamma_v2.md"  # same prefix as f4, different content

        f1.write_text(content_a, encoding="utf-8")
        f2.write_text(content_b, encoding="utf-8")
        f3.write_text(content_b, encoding="utf-8")  # same content as f2
        f4.write_text(content_c, encoding="utf-8")
        f5.write_text(content_d, encoding="utf-8")

        metas = [
            _make_meta(
                f1, file_id="alpha", hash_from_name="h_a", timestamp=100.0
            ),
            _make_meta(
                f2, file_id="beta", hash_from_name="h_b", timestamp=100.0
            ),
            _make_meta(
                f3, file_id="beta", hash_from_name="h_b", timestamp=200.0
            ),
            _make_meta(
                f4, file_id="gamma", hash_from_name="h_g", timestamp=100.0
            ),
            _make_meta(
                f5, file_id="gamma", hash_from_name="h_g", timestamp=200.0
            ),
        ]

        # When
        unique, groups = find_duplicates(metas)

        # Then
        # f1: unique
        # f2, f3: exact duplicates (f3 kept, f2 duplicate)
        # f4, f5: suspected (both kept, flagged)
        assert len(unique) == 4  # f1, f3, f4, f5
        assert len(groups) == 2

        exact_group = next(g for g in groups if g.reason == "exact")
        suspected_group = next(g for g in groups if g.reason == "suspected")

        assert exact_group.kept.path == f3  # latest timestamp
        assert exact_group.duplicates[0].path == f2

        assert suspected_group.similarity == -1.0
        assert len(suspected_group.duplicates) == 1
        # Both gamma files should be in unique
        unique_paths = {m.path for m in unique}
        assert f4 in unique_paths
        assert f5 in unique_paths
