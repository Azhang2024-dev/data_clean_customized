"""Tests for corpus_cleaner.reporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from corpus_cleaner.reporter import generate_report


def _make_file(
    source_folder: str = "用户回流阿语筛选",
    original_name: str = "0Ab_test.md",
    new_name: str = "tutorial_topic_001_S.md",
    category: str = "tutorial",
    primary_lang: str = "AR",
    detected_lang: str = "ar",
    line_count: int = 120,
    raw_char_count: int = 8500,
    net_char_count: int = 7200,
    length_bracket: str = "S",
    table_ratio: float = 0.1,
    contamination_score: float = 0.02,
    status: str = "ok",
    reason: str = "",
) -> dict:
    return {
        "source_folder": source_folder,
        "original_name": original_name,
        "new_name": new_name,
        "category": category,
        "primary_lang": primary_lang,
        "detected_lang": detected_lang,
        "line_count": line_count,
        "raw_char_count": raw_char_count,
        "net_char_count": net_char_count,
        "length_bracket": length_bracket,
        "table_ratio": table_ratio,
        "contamination_score": contamination_score,
        "status": status,
        "reason": reason,
    }


def _sample_results() -> dict:
    """Build a realistic results dict with all categories represented."""
    files = [
        _make_file("用户回流阿语筛选", "0Ab_test.md", "tutorial_topic_001_S.md", "tutorial", "AR", "ar", 120, 8500, 7200, "S", 0.1, 0.02, "ok", ""),
        _make_file("用户回流阿语筛选", "1Bc_long.md", "book_subject_001_L.md", "book", "AR", "ar", 800, 62000, 58000, "L", 0.05, 0.01, "ok", ""),
        _make_file("用户回流阿语筛选", "2Cd_table.md", "table_data_001_M.md", "table", "AR", "ar", 50, 3200, 1200, "S", 0.85, 0.0, "table", "table_ratio=0.85 > 0.70"),
        _make_file("用户回流俄语", "3De_lecture.md", "lecture_topic_001_M.md", "lecture", "RU", "ru", 300, 28000, 25000, "M", 0.08, 0.01, "ok", ""),
        _make_file("用户回流俄语", "4Ef_short.md", "short_note_001_S.md", "short", "RU", "ru", 80, 5500, 4900, "S", 0.0, 0.0, "ok", ""),
        _make_file("用户回流法语_1246篇", "5Fg_exam.md", "exam_quiz_001_M.md", "exam", "FR", "fr", 250, 32000, 28000, "M", 0.02, 0.01, "ok", ""),
        _make_file("用户回流法语_1246篇", "6Gh_book.md", "book_histoire_001_L.md", "book", "FR", "fr", 1200, 95000, 88000, "L", 0.01, 0.0, "ok", ""),
        _make_file("用户回流法语_筛选_200篇", "7Hi_dup.md", "tutorial_dup_001_S.md", "tutorial", "FR", "fr", 150, 12000, 10500, "S", 0.1, 0.01, "ok", ""),
        _make_file("用户回流EN多格式", "8Ij_en1.md", "tutorial_english_001_M.md", "tutorial", "EN", "en", 350, 35000, 31000, "M", 0.15, 0.02, "ok", ""),
        _make_file("用户回流EN多格式", "9Jk_en2.md", "exam_test_001_L.md", "exam", "EN", "en", 600, 56000, 52000, "L", 0.01, 0.0, "ok", ""),
        _make_file("用户回流阿语筛选", "0Kk_bad.md", "", "misc", "AR", "", 0, 0, 0, "", 0, 0, "bad", "UnicodeDecodeError"),
        _make_file("用户回流阿语筛选", "1Ll_empty.md", "", "misc", "AR", "", 0, 0, 0, "", 0, 0, "empty", "line_count=0"),
    ]
    return {
        "files": files,
        "contaminated": [
            {"filename": "0Co_contam.md", "score": 0.12, "sample_lines": "Line 1: 炎症IDE\nLine 2: Neoesar text\nLine 3: normal text"},
        ],
        "duplicates": [
            {"kept_name": "dup_v2.md", "duplicate_names": ["dup_v1.md"], "similarity": 1.0},
            {"kept_name": "sus_v2.md", "duplicate_names": ["sus_v1.md"], "similarity": -1.0},
        ],
        "bad_files": [
            {"filename": "02h_binary.md", "error": "UTF-8 decode failed"},
        ],
        "stats": {},
    }


class TestGenerateReportCreatesFiles:
    def test_creates_all_three_output_files(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        assert (tmp_path / "_report.xlsx").exists()
        assert (tmp_path / "_summary.txt").exists()
        assert (tmp_path / "_original_manifest.json").exists()


class TestExcelStructure:
    def test_all_six_worksheets_present(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        sheet_names = wb.sheetnames

        expected = {
            "Summary",
            "FileDetails",
            "ContaminatedFiles",
            "Duplicates",
            "BadFiles",
            "LengthDistribution",
        }
        assert set(sheet_names) == expected

    def test_file_details_has_fourteen_columns(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["FileDetails"]

        headers = [ws.cell(row=1, column=c).value for c in range(1, 15)]
        expected = [
            "source_folder",
            "original_name",
            "new_name",
            "category",
            "primary_lang",
            "detected_lang",
            "line_count",
            "raw_char_count",
            "net_char_count",
            "length_bracket",
            "table_ratio",
            "contamination_score",
            "status",
            "reason",
        ]
        assert headers == expected

    def test_file_details_row_count_matches_input(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["FileDetails"]
        # Header row 1 + 12 data rows
        assert ws.max_row == 13  # 1 header + 12 files

    def test_contaminated_sheet_has_sample_lines(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["ContaminatedFiles"]

        assert ws.cell(row=2, column=1).value == "0Co_contam.md"
        assert ws.cell(row=2, column=2).value == 0.12
        assert "炎症IDE" in str(ws.cell(row=2, column=3).value)

    def test_duplicates_sheet_has_correct_data(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["Duplicates"]

        assert ws.cell(row=2, column=1).value == "dup_v2.md"
        assert ws.cell(row=2, column=2).value == "dup_v1.md"
        assert ws.cell(row=2, column=3).value == 1.0
        assert ws.cell(row=3, column=1).value == "sus_v2.md"

    def test_bad_files_sheet_has_correct_data(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["BadFiles"]

        assert ws.cell(row=2, column=1).value == "02h_binary.md"
        assert "UTF-8" in str(ws.cell(row=2, column=2).value)


class TestLengthDistribution:
    def test_pivot_table_has_language_rows_and_bracket_columns(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["LengthDistribution"]

        # Header: Language | S | M | L | S% | M% | L% | Total
        headers = [ws.cell(row=1, column=c).value for c in range(1, 9)]
        assert headers == ["Language", "S", "M", "L", "S%", "M%", "L%", "Total"]

        # AR row: 2 S, 0 M, 2 L, 2 bad/empty files excluded from bracket counts
        assert ws.cell(row=2, column=1).value == "AR"
        # Files: 0Ab (S), 1Bc (L), 2Cd (S), 0Kk (bad, no bracket), 1Ll (empty, no bracket)
        # With bracket: S=2 (0Ab, 2Cd), M=0, L=1 (1Bc)
        assert ws.cell(row=2, column=2).value == 2  # S
        assert ws.cell(row=2, column=3).value == 0  # M
        assert ws.cell(row=2, column=4).value == 1  # L
        assert ws.cell(row=2, column=8).value == 5  # Total AR files

        # sorted_langs = AR, EN, FR, ID, RU (alphabetical, includes LANGUAGES)
        # EN row: 1 M, 1 L
        assert ws.cell(row=3, column=1).value == "EN"
        assert ws.cell(row=3, column=2).value == 0  # S
        assert ws.cell(row=3, column=3).value == 1  # M
        assert ws.cell(row=3, column=4).value == 1  # L
        assert ws.cell(row=3, column=8).value == 2  # Total

        # FR row: 1 S, 1 M, 1 L
        assert ws.cell(row=4, column=1).value == "FR"
        assert ws.cell(row=4, column=2).value == 1  # S
        assert ws.cell(row=4, column=3).value == 1  # M
        assert ws.cell(row=4, column=4).value == 1  # L
        assert ws.cell(row=4, column=8).value == 3  # Total

        # ID row: 0 files
        assert ws.cell(row=5, column=1).value == "ID"
        assert ws.cell(row=5, column=8).value == 0  # Total

        # RU row: 1 S, 1 M, 0 L
        assert ws.cell(row=6, column=1).value == "RU"
        assert ws.cell(row=6, column=2).value == 1  # S
        assert ws.cell(row=6, column=3).value == 1  # M
        assert ws.cell(row=6, column=4).value == 0  # L
        assert ws.cell(row=6, column=8).value == 2  # Total

    def test_percentage_columns_have_format(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        wb = load_workbook(tmp_path / "_report.xlsx")
        ws = wb["LengthDistribution"]

        assert ws.cell(row=2, column=5).number_format == "0.0%"


class TestSummaryText:
    def test_summary_contains_expected_sections(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        content = (tmp_path / "_summary.txt").read_text(encoding="utf-8")

        assert "语料清洗报告" in content
        assert "总处理文件数: 12" in content
        assert "OCR 污染文件: 1" in content
        assert "重复组数: 2" in content
        assert "损坏文件: 1" in content
        assert "按语言统计:" in content
        assert "按状态统计:" in content
        assert "按长度（移动端参考，单位：净字符）:" in content
        assert "移动端需分页/截断" in content

    def test_summary_language_distribution_format(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        content = (tmp_path / "_summary.txt").read_text(encoding="utf-8")

        assert "AR: S=" in content
        assert "RU: S=" in content
        assert "FR: S=" in content
        assert "EN: S=" in content


class TestManifest:
    def test_manifest_maps_original_to_new_names(self, tmp_path: Path) -> None:
        results = _sample_results()
        generate_report(results, str(tmp_path))

        manifest = json.loads((tmp_path / "_original_manifest.json").read_text(encoding="utf-8"))

        assert "0Ab_test.md" in manifest
        assert manifest["0Ab_test.md"]["new_name"] == "tutorial_topic_001_S.md"
        assert manifest["0Ab_test.md"]["category"] == "tutorial"
        assert manifest["0Ab_test.md"]["primary_lang"] == "AR"
        assert manifest["0Ab_test.md"]["length_bracket"] == "S"

    def test_manifest_excludes_empty_original_names(self, tmp_path: Path) -> None:
        results = _sample_results()
        results["files"].append(
            _make_file(
                source_folder="用户回流阿语筛选",
                original_name="",
                new_name="",
                primary_lang="AR",
            )
        )
        generate_report(results, str(tmp_path))

        manifest = json.loads((tmp_path / "_original_manifest.json").read_text(encoding="utf-8"))

        assert "" not in manifest
        assert len(manifest) == 12  # 13 total, 1 with empty original_name excluded
        assert "0Ab_test.md" in manifest

    def test_manifest_preserves_unicode(self, tmp_path: Path) -> None:
        results = _sample_results()
        # Add a file with Unicode in original_name
        results["files"].append(
            _make_file(
                source_folder="用户回流阿语筛选",
                original_name="اختبار_arabe.md",
                new_name="book_arabic_001_L.md",
                primary_lang="AR",
                detected_lang="ar",
                length_bracket="L",
            )
        )
        generate_report(results, str(tmp_path))

        raw = (tmp_path / "_original_manifest.json").read_bytes()
        assert "اختبار_arabe.md".encode("utf-8") in raw


class TestEmptyInput:
    def test_empty_files_list_produces_valid_outputs(self, tmp_path: Path) -> None:
        results: dict = {
            "files": [],
            "contaminated": [],
            "duplicates": [],
            "bad_files": [],
        }
        generate_report(results, str(tmp_path))

        assert (tmp_path / "_report.xlsx").exists()
        assert (tmp_path / "_summary.txt").exists()
        assert (tmp_path / "_original_manifest.json").exists()

        wb = load_workbook(tmp_path / "_report.xlsx")
        assert set(wb.sheetnames) == {
            "Summary", "FileDetails", "ContaminatedFiles",
            "Duplicates", "BadFiles", "LengthDistribution",
        }

        ws = wb["FileDetails"]
        assert ws.max_row == 1  # Only header

        content = (tmp_path / "_summary.txt").read_text(encoding="utf-8")
        assert "总处理文件数: 0" in content

        manifest = json.loads((tmp_path / "_original_manifest.json").read_text(encoding="utf-8"))
        assert manifest == {}
