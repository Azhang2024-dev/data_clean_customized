"""Smoke test — end-to-end pipeline dry-run against real or synthetic Arabic corpus data.

Verifies:
    1. Pipeline completes without error
    2. _report.xlsx exists and has 6 worksheets
    3. _summary.txt exists and contains expected sections
    4. _original_manifest.json exists and is valid JSON
    5. File counts are reasonable
    6. No output subdirectories created (dry-run mode)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.utils.exceptions import IllegalCharacterError

from corpus_cleaner.config import PipelineConfig
from corpus_cleaner.pipeline import run_pipeline

# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

_REAL_BASE = Path(
    "D:/Users/admin/Desktop/My Project/Ella知识库数据集/语料清理文件及软件输出"
)
_REAL_AR_FOLDER = "用户回流阿语筛选"

EXPECTED_SHEET_NAMES = [
    "Summary",
    "FileDetails",
    "ContaminatedFiles",
    "Duplicates",
    "BadFiles",
    "LengthDistribution",
]

EXPECTED_SUMMARY_SECTIONS = [
    "语料清洗报告",
    "总处理文件数",
    "OCR 污染文件",
    "重复组数",
    "损坏文件",
    "按语言统计",
    "按状态统计",
    "按长度",
]


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_synthetic_ar_corpus(base: Path) -> Path:
    """Create a synthetic Arabic corpus directory with ~20 sample .md files.

    Covers: clean Arabic, table-dominant, CJK-contaminated, duplicate content,
    empty, and bad-encoding files.
    """
    ar_dir = base / _REAL_AR_FOLDER
    ar_dir.mkdir(parents=True)

    # Clean Arabic documents — tutorial and exam styles.
    (ar_dir / "tutorial_20240601_001_aaa11111.md").write_text(
        "# مقدمة في البرمجة بلغة بايثون\n\n"
        "هذا درس تعليمي يحتوي على أمثلة برمجية.\n\n"
        "## المتغيرات\n"
        "```python\n"
        "x = 10\n"
        "y = 20\n"
        "print(x + y)\n"
        "```\n\n"
        "## الدوال\n"
        "الدوال هي وحدات برمجية قابلة لإعادة الاستخدام.\n",
        encoding="utf-8",
    )

    (ar_dir / "exam_20240602_002_bbb22222.md").write_text(
        "# امتحان اللغة العربية\n\n"
        "أجب عن الأسئلة التالية:\n\n"
        "A) ما هو الفعل المضارع؟\n"
        "B) عرف المبتدأ والخبر.\n"
        "C) اذكر أنواع الخبر.\n"
        "D) ما هي علامات الإعراب الأصلية؟\n\n"
        "☐ السؤال الأول: اختر الإجابة الصحيحة.\n"
        "☐ السؤال الثاني: صحح الخطأ.\n",
        encoding="utf-8",
    )

    (ar_dir / "lecture_20240603_003_ccc33333.md").write_text(
        "# محاضرة في النحو العربي\n\n"
        "## المقدمة\n"
        "• النحو هو علم يبحث في أصول تكوين الجملة.\n"
        "• قواعد الإعراب تحدد وظيفة الكلمة في الجملة.\n"
        "• البناء هو لزوم آخر الكلمة حالة واحدة.\n\n"
        "## الفاعل\n"
        "• الفاعل هو اسم مرفوع تقدمه فعل.\n"
        "• يأتي الفاعل بعد الفعل مباشرة.\n",
        encoding="utf-8",
    )

    (ar_dir / "book_20240604_004_ddd44444.md").write_text(
        "# كتاب النحو الوافي\n\n"
        "## الباب الأول: الكلمة وأقسامها\n"
        "تنقسم الكلمة في اللغة العربية إلى اسم وفعل وحرف.\n\n"
        "### الاسم\n"
        "الاسم هو ما دل على معنى في نفسه غير مقترن بزمن.\n\n"
        "### الفعل\n"
        "الفعل هو ما دل على معنى مقترن بزمن.\n\n"
        "### الحرف\n"
        "الحرف هو ما دل على معنى في غيره.\n",
        encoding="utf-8",
    )

    # Short document.
    (ar_dir / "short_20240605_005_eee55555.md").write_text(
        "# نص قصير\n\nهذا نص قصير جدا للاختبار.\n",
        encoding="utf-8",
    )

    # Table-dominant file (>70% <table> lines).
    (ar_dir / "table_20240606_006_fff66666.md").write_text(
        "<table>\n<tr><td>بيانات</td></tr>\n</table>\n"
        "<table>\n<tr><td>مزيد</td></tr>\n</table>\n"
        "<table>\n<tr><td>جداول</td></tr>\n</table>\n"
        "<table>\n<tr><td>كثيرة</td></tr>\n</table>\n"
        "نص عادي واحد فقط.\n",
        encoding="utf-8",
    )

    # CJK-contaminated file.
    (ar_dir / "contam_20240607_007_ggg77777.md").write_text(
        "# درس في النحو\n\n"
        "هذا النص يحتوي 日本語 على تلوث 中文 من نوع OCR.\n"
        "الجملة الثانية 漢字 أيضا ملوثة.\n"
        "日本語の文字が混ざっています。\n",
        encoding="utf-8",
    )

    # Duplicate content (same as book_20240604).
    (ar_dir / "book_copy_20240608_008_hhh88888.md").write_text(
        "# كتاب النحو الوافي\n\n"
        "## الباب الأول: الكلمة وأقسامها\n"
        "تنقسم الكلمة في اللغة العربية إلى اسم وفعل وحرف.\n\n"
        "### الاسم\n"
        "الاسم هو ما دل على معنى في نفسه غير مقترن بزمن.\n\n"
        "### الفعل\n"
        "الفعل هو ما دل على معنى مقترن بزمن.\n\n"
        "### الحرف\n"
        "الحرف هو ما دل على معنى في غيره.\n",
        encoding="utf-8",
    )

    # Empty file.
    (ar_dir / "empty_20240609_009_iii99999.md").write_text("", encoding="utf-8")

    # More clean Arabic documents to reach ~20 files.
    for i in range(10, 21):
        name = f"doc{i:02d}_20240610_{i:03d}_xxx{i:05d}.md"
        (ar_dir / name).write_text(
            f"# المستند رقم {i}\n\n"
            f"هذا هو المستند رقم {i} في مجموعة الاختبار.\n\n"
            f"## الفقرة الأولى\n"
            f"نص تجريبي للاختبار رقم {i}.\n",
            encoding="utf-8",
        )

    return base


def _is_real_data_available() -> bool:
    """Check whether the real Arabic corpus folder exists."""
    return (_REAL_BASE / _REAL_AR_FOLDER).is_dir()


def _run_pipeline_on_synthetic(tmp_path: Path) -> tuple[Path, dict]:
    """Run pipeline on synthetic AR data, return (output_dir, results)."""
    input_path = str(_make_synthetic_ar_corpus(tmp_path))
    output_dir = tmp_path / "output"
    config = PipelineConfig(
        input_path=input_path,
        output_path=str(output_dir),
        dry_run=True,
    )
    results = run_pipeline(config)
    return output_dir, results


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Synthetic Data (primary, always passes)
# ══════════════════════════════════════════════════════════════════════════════


class TestSmokeSynthetic:
    """Given a synthetic Arabic corpus directory with 21 files,
    When run_pipeline() executes in dry-run mode,
    Then the pipeline completes and produces correct report artifacts.
    """

    def test_pipeline_completes_without_error(self) -> None:
        """Pipeline dry-run against synthetic AR corpus completes without exception."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, results = _run_pipeline_on_synthetic(Path(tmp))
            assert results is not None
            assert "stats" in results
            assert "files" in results

    def test_report_xlsx_has_six_worksheets(self) -> None:
        """_report.xlsx exists with all 6 expected sheets."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _results = _run_pipeline_on_synthetic(Path(tmp))

            xlsx_path = output_dir / "_report.xlsx"
            assert xlsx_path.exists(), f"_report.xlsx not found at {xlsx_path}"

            wb = load_workbook(str(xlsx_path), read_only=True)
            sheet_names = wb.sheetnames
            wb.close()

            for expected in EXPECTED_SHEET_NAMES:
                assert expected in sheet_names, (
                    f"Missing sheet {expected!r} in {sheet_names}"
                )
            assert len(sheet_names) == 6, (
                f"Expected 6 sheets, got {len(sheet_names)}: {sheet_names}"
            )

    def test_summary_txt_has_expected_sections(self) -> None:
        """_summary.txt exists and contains all required sections."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _results = _run_pipeline_on_synthetic(Path(tmp))

            summary_path = output_dir / "_summary.txt"
            assert summary_path.exists(), (
                f"_summary.txt not found at {summary_path}"
            )

            text = summary_path.read_text(encoding="utf-8")

            for section in EXPECTED_SUMMARY_SECTIONS:
                assert section in text, (
                    f"Missing section {section!r} in _summary.txt"
                )

    def test_manifest_json_is_valid(self) -> None:
        """_original_manifest.json exists and is valid JSON with expected keys."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _results = _run_pipeline_on_synthetic(Path(tmp))

            manifest_path = output_dir / "_original_manifest.json"
            assert manifest_path.exists(), (
                f"_original_manifest.json not found at {manifest_path}"
            )

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict), "Manifest root is not a dict"
            assert len(data) > 0, "Manifest is empty"

            expected_entry_keys = {
                "new_name", "category", "primary_lang",
                "length_bracket", "status",
            }
            for original_name, entry in data.items():
                assert isinstance(entry, dict), (
                    f"Entry for {original_name!r} is not a dict"
                )
                for key in expected_entry_keys:
                    assert key in entry, (
                        f"Missing key {key!r} in manifest entry for {original_name!r}"
                    )

    def test_file_count_reasonable(self) -> None:
        """Scanned file count matches synthetic dataset (21 files)."""
        with tempfile.TemporaryDirectory() as tmp:
            _output_dir, results = _run_pipeline_on_synthetic(Path(tmp))

            total = results["stats"]["total_scanned"]
            assert 15 <= total <= 25, (
                f"Expected 15-25 files for synthetic data, got {total}"
            )

    def test_no_subdirectories_in_dry_run(self) -> None:
        """Dry-run mode creates no language or isolation subdirectories."""
        with tempfile.TemporaryDirectory() as tmp:
            output_dir, _results = _run_pipeline_on_synthetic(Path(tmp))

            lang_dirs = [
                d for d in output_dir.iterdir()
                if d.is_dir() and d.name in ("AR", "RU", "FR", "EN")
            ]
            assert len(lang_dirs) == 0, (
                f"Language directories should not exist in dry-run: {lang_dirs}"
            )

    def test_results_file_records_have_required_fields(self) -> None:
        """Every file record in results has all 14 required fields."""
        with tempfile.TemporaryDirectory() as tmp:
            _output_dir, results = _run_pipeline_on_synthetic(Path(tmp))

            required_fields = [
                "source_folder", "original_name", "new_name",
                "category", "primary_lang", "detected_lang",
                "line_count", "raw_char_count", "net_char_count",
                "length_bracket", "table_ratio", "contamination_score",
                "status", "reason",
            ]

            for rec in results["files"]:
                for field in required_fields:
                    assert field in rec, (
                        f"Missing field {field!r} in file record for "
                        f"{rec.get('original_name', '?')}"
                    )

    def test_stats_are_internally_consistent(self) -> None:
        """Stats counts sum correctly and match file record count."""
        with tempfile.TemporaryDirectory() as tmp:
            _output_dir, results = _run_pipeline_on_synthetic(Path(tmp))

            stats = results["stats"]
            files = results["files"]

            status_sum = (
                stats["passed"]
                + stats["bad"]
                + stats["empty"]
                + stats["table"]
                + stats["contaminated"]
                + stats["duplicates_total"]
                + stats.get("html_noisy", 0)
                + stats.get("image_only", 0)
            )
            assert status_sum == stats["total_scanned"], (
                f"Status sum {status_sum} != total_scanned {stats['total_scanned']}"
            )

            assert len(files) == stats["total_scanned"], (
                f"File records {len(files)} != total_scanned {stats['total_scanned']}"
            )


class TestSmokeCLI:
    """Given the synthetic Arabic corpus,
    When the CLI entry point is invoked with --dry-run,
    Then it exits successfully and produces report artifacts.
    """

    def test_cli_dry_run_exits_zero(self) -> None:
        """CLI --dry-run against synthetic AR corpus returns exit code 0."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = str(_make_synthetic_ar_corpus(tmp_path))
            output_dir = tmp_path / "output"

            cmd = [
                sys.executable, "corpus_clean.py",
                "--input", input_path,
                "--output", str(output_dir),
                "--dry-run",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent.parent),
            )

            assert result.returncode == 0, (
                f"CLI exited with {result.returncode}\n"
                f"stderr: {result.stderr}\n"
                f"stdout: {result.stdout[-500:]}"
            )

            assert "Corpus Cleaning Complete" in result.stdout
            assert "[Dry run — no files were written]" in result.stdout

            assert (output_dir / "_report.xlsx").exists()
            assert (output_dir / "_summary.txt").exists()
            assert (output_dir / "_original_manifest.json").exists()


class TestSmokeSpotCheck:
    """Given the pipeline results from the synthetic AR corpus,
    When we manually inspect 20 file records,
    Then the records are well-formed and plausible.
    """

    def test_spot_check_20_records(self) -> None:
        """Spot-check up to 20 file records for data integrity."""
        with tempfile.TemporaryDirectory() as tmp:
            _output_dir, results = _run_pipeline_on_synthetic(Path(tmp))

            files = results["files"]
            sample = files[:20] if len(files) >= 20 else files

            assert len(sample) > 0, "No file records to spot-check"

            categories_seen: set[str] = set()
            statuses_seen: set[str] = set()
            langs_seen: set[str] = set()

            for rec in sample:
                assert rec["original_name"], "File record has empty original_name"

                assert rec["status"] in (
                    "ok", "table", "contaminated", "duplicate", "empty", "bad", "html_noisy", "image_only"
                ), f"Unknown status {rec['status']!r}"

                assert rec["primary_lang"], "File record has empty primary_lang"

                assert isinstance(rec["line_count"], int)
                if rec["status"] != "bad":
                    assert rec["line_count"] >= 0, (
                        f"Negative line_count for non-bad file: {rec['line_count']}"
                    )

                assert isinstance(rec["net_char_count"], int)
                assert isinstance(rec["table_ratio"], (int, float))
                if rec["status"] != "bad":
                    assert 0.0 <= rec["table_ratio"] <= 1.0, (
                        f"table_ratio out of range: {rec['table_ratio']}"
                    )

                assert isinstance(rec["contamination_score"], (int, float))
                assert 0.0 <= rec["contamination_score"] <= 1.0, (
                    f"contamination_score out of range: {rec['contamination_score']}"
                )

                assert rec["length_bracket"] in ("S", "M", "L"), (
                    f"Invalid length_bracket: {rec['length_bracket']!r}"
                )

                assert rec["source_folder"], "File record has empty source_folder"

                categories_seen.add(rec["category"])
                statuses_seen.add(rec["status"])
                langs_seen.add(rec["primary_lang"])

            assert len(categories_seen) > 0
            assert len(statuses_seen) > 0
            assert "AR" in langs_seen, (
                f"Expected AR language in results, got {langs_seen}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Real Data
# ══════════════════════════════════════════════════════════════════════════════


class TestSmokeRealData:
    """Given the real Arabic corpus folder (~418 files),
    When run_pipeline() executes in dry-run mode,
    Then the pipeline completes without error.
    """

    def test_pipeline_completes_on_real_data(self) -> None:
        """Pipeline dry-run against real AR corpus."""
        if not _is_real_data_available():
            pytest.skip("Real AR corpus folder not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            config = PipelineConfig(
                input_path=str(_REAL_BASE),
                output_path=str(output_dir),
                folders=[_REAL_AR_FOLDER],
                dry_run=True,
            )
            results = run_pipeline(config)

            assert results is not None
            assert results["stats"]["total_scanned"] > 300

    def test_real_data_file_count(self) -> None:
        """Real AR corpus should have ~418 files."""
        if not _is_real_data_available():
            pytest.skip("Real AR corpus folder not available")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            config = PipelineConfig(
                input_path=str(_REAL_BASE),
                output_path=str(output_dir),
                folders=[_REAL_AR_FOLDER],
                dry_run=True,
            )
            results = run_pipeline(config)

            total = results["stats"]["total_scanned"]
            assert 300 <= total <= 500, (
                f"Expected 300-500 files for real AR corpus, got {total}"
            )
