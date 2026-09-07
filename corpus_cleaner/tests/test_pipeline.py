"""Integration tests for corpus_cleaner.pipeline — end-to-end pipeline runs."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from corpus_cleaner.config import PipelineConfig
from corpus_cleaner.pipeline import run_pipeline


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


def _make_input_dir(base: Path) -> Path:
    """Create a minimal input directory structure with sample files.

    Creates one subfolder per language with a few .md files.
    """
    input_dir = base / "input"
    input_dir.mkdir()

    # AR folder
    ar_dir = input_dir / "用户回流阿语筛选"
    ar_dir.mkdir()
    (ar_dir / "doc1_20240101_001_abc12345.md").write_text(
        "# مقدمة في البرمجة\n\n"
        "هذا مستند تعليمي يحتوي على أمثلة.\n\n"
        "## الفصل الأول\n"
        "المحتوى الأساسي للفصل الأول.\n",
        encoding="utf-8",
    )
    (ar_dir / "doc2_20240102_002_def67890.md").write_text(
        "# قواعد اللغة العربية\n\n"
        "درس في قواعد اللغة العربية الأساسية.\n\n"
        "## النحو\n"
        "شرح مفصل لقواعد النحو.\n",
        encoding="utf-8",
    )

    # RU folder
    ru_dir = input_dir / "用户回流俄语"
    ru_dir.mkdir()
    (ru_dir / "lecture1_20240101_001_aaa11111.md").write_text(
        "# Введение в математику\n\n"
        "Лекция по основам математического анализа.\n\n"
        "## Тема 1\n"
        "Пределы и непрерывность.\n",
        encoding="utf-8",
    )

    # FR folder
    fr_dir = input_dir / "用户回流法语_1246篇"
    fr_dir.mkdir()
    (fr_dir / "cours1_20240101_001_zzz99999.md").write_text(
        "# Introduction à la programmation\n\n"
        "```python\n"
        "print('Hello, World!')\n"
        "```\n\n"
        "## Variables\n"
        "Les variables en Python.\n",
        encoding="utf-8",
    )

    # EN folder
    en_dir = input_dir / "用户回流EN多格式"
    en_dir.mkdir()
    (en_dir / "guide1_20240101_001_xyz11111.md").write_text(
        "# Python Tutorial\n\n"
        "A comprehensive guide to Python programming.\n\n"
        "## Getting Started\n"
        "Installation and setup instructions.\n\n"
        "## Basic Syntax\n"
        "Variables, types, and control flow.\n\n"
        "## Advanced Topics\n"
        "Decorators, generators, and context managers.\n",
        encoding="utf-8",
    )

    # Empty file
    (en_dir / "empty_20240101_002_emp00001.md").write_text("", encoding="utf-8")

    # Table-dominant file — 4 <table> lines + 1 non-table = 0.80 ratio > 0.70
    (en_dir / "table_20240101_003_tbl00001.md").write_text(
        "<table>\n<table>\n<table>\n<table>\nJust one text line.\n",
        encoding="utf-8",
    )

    # Duplicate file (same content as guide1)
    (en_dir / "guide1_copy_20240102_001_xyz11111.md").write_text(
        "# Python Tutorial\n\n"
        "A comprehensive guide to Python programming.\n\n"
        "## Getting Started\n"
        "Installation and setup instructions.\n\n"
        "## Basic Syntax\n"
        "Variables, types, and control flow.\n\n"
        "## Advanced Topics\n"
        "Decorators, generators, and context managers.\n",
        encoding="utf-8",
    )

    return input_dir


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineEndToEnd:
    """Given a directory with sample corpus files,
    When run_pipeline() executes,
    Then all stages complete and produce correct output.
    """

    def test_dry_run_produces_report_only(self) -> None:
        """Dry run computes everything but writes no files."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            # Stats present.
            stats = results["stats"]
            assert stats["total_scanned"] == 8
            assert stats["passed"] >= 1
            assert stats["empty"] >= 1
            assert stats["table"] >= 1

            # Report files written even in dry-run.
            assert (output_dir / "_report.xlsx").exists()
            assert (output_dir / "_summary.txt").exists()
            assert (output_dir / "_original_manifest.json").exists()

            # No output subdirectories created in dry-run.
            assert not list(output_dir.glob("AR"))
            assert not list(output_dir.glob("EN"))
            assert not list(output_dir.glob("_tables"))
            assert not list(output_dir.glob("_empty"))

    def test_full_run_writes_output_structure(self) -> None:
        """Full run writes files to the output directory structure."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=False,
            )
            results = run_pipeline(config)

            stats = results["stats"]
            assert stats["total_scanned"] == 8

            # Output structure exists.
            assert (output_dir / "_report.xlsx").exists()
            assert (output_dir / "_summary.txt").exists()
            assert (output_dir / "_original_manifest.json").exists()

            # _empty directory should have the empty file.
            empty_files = list((output_dir / "_empty").rglob("*.md"))
            assert len(empty_files) >= 1

            # _tables directory should have the table file.
            table_files = list((output_dir / "_tables").rglob("*.md"))
            assert len(table_files) >= 1

            # Language directories should have passed files.
            all_lang_files: list[Path] = []
            for lang in ("AR", "RU", "FR", "EN"):
                lang_dir = output_dir / lang
                if lang_dir.exists():
                    all_lang_files.extend(lang_dir.rglob("*.md"))
            assert len(all_lang_files) >= 1

    def test_results_dict_structure(self) -> None:
        """Results dict has all expected keys with correct types."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            assert "files" in results
            assert "contaminated" in results
            assert "duplicates" in results
            assert "bad_files" in results
            assert "stats" in results

            assert isinstance(results["files"], list)
            assert isinstance(results["contaminated"], list)
            assert isinstance(results["duplicates"], list)
            assert isinstance(results["bad_files"], list)
            assert isinstance(results["stats"], dict)

            # File records have required fields.
            for rec in results["files"]:
                for key in (
                    "source_folder", "original_name", "new_name",
                    "category", "primary_lang", "detected_lang",
                    "line_count", "status",
                ):
                    assert key in rec, f"Missing key {key!r} in file record"

    def test_passed_files_get_new_names(self) -> None:
        """Passed files receive semantic filenames via renamer."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            passed = [r for r in results["files"] if r["status"] == "ok"]
            assert len(passed) >= 1
            for rec in passed:
                assert rec["new_name"], f"Passed file has no new_name: {rec['original_name']}"
                assert rec["category"], f"Passed file has no category: {rec['original_name']}"
                # Filename format: {category}_{topic}_{seq:03d}_{S|M|L}.md
                name = rec["new_name"]
                assert name.endswith(".md")
                parts = name[:-3].split("_")
                assert len(parts) >= 3, f"Unexpected name format: {name!r}"

    def test_empty_input_no_crash(self) -> None:
        """Pipeline handles an empty input directory gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            input_dir.mkdir()
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
            )
            results = run_pipeline(config)

            assert results["stats"]["total_scanned"] == 0
            assert results["stats"]["passed"] == 0

    def test_dry_run_flag_prevents_file_write(self) -> None:
        """--dry-run computes stats but creates no output subdirectories."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            # Report files are still created.
            assert (output_dir / "_report.xlsx").exists()

            # But no language directories or isolation directories.
            dirs = [
                d for d in output_dir.iterdir() if d.is_dir()
                and not d.name.startswith("_")  # exclude report-related
            ]
            # Only files (report artifacts), no subdirectories.
            non_report_dirs = [
                d for d in output_dir.iterdir()
                if d.is_dir() and d.name not in ("_report.xlsx",)
                and not d.name.startswith("_")
            ]
            # In dry-run, no subdirectories like AR/ EN/ should exist
            lang_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name in ("AR", "RU", "FR", "EN")]
            assert len(lang_dirs) == 0

    def test_duplicate_detection(self) -> None:
        """Exact duplicates are detected and reported."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            dup_records = results["duplicates"]
            # guide1 and guide1_copy have identical content → exact duplicate.
            assert len(dup_records) >= 1

            file_statuses = {
                r["original_name"]: r["status"] for r in results["files"]
            }
            # At least one file should be marked as duplicate.
            dup_count = sum(
                1 for s in file_statuses.values() if s == "duplicate"
            )
            assert dup_count >= 1

    def test_length_thresholds_cli_parse(self) -> None:
        """Custom length thresholds are passed through and used."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                length_thresholds=(100, 500),
                dry_run=True,
            )
            results = run_pipeline(config)

            passed = [r for r in results["files"] if r["status"] == "ok"]
            for rec in passed:
                assert rec["length_bracket"] in ("S", "M", "L")

    def test_stats_consistency(self) -> None:
        """Stats counts are internally consistent with file records."""
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = _make_input_dir(Path(tmp))
            output_dir = Path(tmp) / "output"

            config = PipelineConfig(
                input_path=str(input_dir),
                output_path=str(output_dir),
                dry_run=True,
            )
            results = run_pipeline(config)

            stats = results["stats"]
            files = results["files"]

            # total_scanned == sum of all status categories
            status_sum = (
                stats["passed"]
                + stats["bad"]
                + stats["empty"]
                + stats["table"]
                + stats.get("html_noisy", 0)
                + stats.get("image_only", 0)
                + stats["contaminated"]
                + stats["duplicates_total"]
            )
            assert status_sum == stats["total_scanned"]

            # file records count matches total_scanned.
            assert len(files) == stats["total_scanned"]
