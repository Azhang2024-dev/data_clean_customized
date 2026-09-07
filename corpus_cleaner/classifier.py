"""File classifier — categorizes corpus files by type using heuristic rules.

Seven categories, evaluated in priority order (first match wins):
  1. exam      — multiple-choice or checkbox patterns
  2. tutorial  — contains triple-backtick code blocks
  3. book      — long document with 3+ heading levels
  4. lecture   — medium-length with dense lists or lecture keywords
  5. short     — fewer than 100 lines, no higher-priority match
  6. table     — table_ratio exceeds threshold (Stage 2 fallback)
  7. misc      — catch-all fallback
"""

from __future__ import annotations

import re

_RE_EXAM_CHOICE = re.compile(r"[A-D][.)]")
_RE_EXAM_CHECKBOX = re.compile(r"☐")

_RE_CODE_BLOCK = re.compile(r"```")

_RE_H1 = re.compile(r"^# ", re.MULTILINE)
_RE_H2 = re.compile(r"^## ", re.MULTILINE)
_RE_H3 = re.compile(r"^### ", re.MULTILINE)

_RE_LIST_MARKER = re.compile(r"^[\*\-•] ", re.MULTILINE)

_RE_LECTURE_KEYWORD = re.compile(r"سكشن|lecture|محاضرة", re.IGNORECASE)


def classify_file(meta: dict, content: str) -> str:
    """Classify a file into one of seven categories based on metadata and content.

    Priority order (first match wins):
      1. exam      — ≥5 choice markers (A./B./C./D. etc.) or ☐ checkboxes
      2. tutorial  — contains triple-backtick code fence
      3. book      — >500 lines AND headings at levels 1, 2, and 3
      4. lecture   — 100–500 lines AND (dense lists OR lecture keywords)
      5. short     — <100 lines
      6. table     — table_ratio > 0.70 (Stage 2 fallback)
      7. misc      — catch-all

    Args:
        meta: Dict with keys 'line_count' (int) and 'table_ratio' (float).
        content: The full file content as a string.

    Returns:
        One of: 'exam', 'tutorial', 'book', 'lecture', 'short', 'table', 'misc'.
    """
    line_count: int = meta.get("line_count", 0)

    if _has_exam_pattern(content):
        return "exam"

    if _has_code_block(content):
        return "tutorial"

    if _has_book_structure(content, line_count):
        return "book"

    if _has_lecture_features(content, line_count):
        return "lecture"

    if line_count < 100:
        return "short"

    table_ratio: float = meta.get("table_ratio", 0.0)
    if table_ratio > 0.70:
        return "table"

    return "misc"


def _has_exam_pattern(content: str) -> bool:
    """Return True when the combined count of exam markers (A./B./C./D., A)/B)/C)/D), ☐) is ≥5."""
    choice_count = len(_RE_EXAM_CHOICE.findall(content))
    checkbox_count = len(_RE_EXAM_CHECKBOX.findall(content))
    return (choice_count + checkbox_count) >= 5


def _has_code_block(content: str) -> bool:
    """Return True when content contains a triple-backtick code fence."""
    return bool(_RE_CODE_BLOCK.search(content))


def _has_book_structure(content: str, line_count: int) -> bool:
    """Return True when line_count > 500 and headings at levels 1, 2, and 3 are all present."""
    if line_count <= 500:
        return False
    has_h1 = bool(_RE_H1.search(content))
    has_h2 = bool(_RE_H2.search(content))
    has_h3 = bool(_RE_H3.search(content))
    return has_h1 and has_h2 and has_h3


def _has_lecture_features(content: str, line_count: int) -> bool:
    if line_count < 100 or line_count > 500:
        return False

    if _RE_LECTURE_KEYWORD.search(content):
        return True

    lines = content.split("\n")
    if len(lines) == 0:
        return False
    list_lines = sum(1 for line in lines if _RE_LIST_MARKER.match(line))
    return (list_lines / len(lines)) > 0.10



# ══════════════════════════════════════════════════════════════════════════════
# Scoring-based classifier (standard/thorough profiles)
# ══════════════════════════════════════════════════════════════════════════════

# Language-aware keyword weights for lecture detection.
_LECTURE_KEYWORDS: dict[str, list[str]] = {
    "AR": ["سكشن", "محاضرة", "درس", "فصل", "وحدة"],
    "RU": ["лекция", "раздел", "глава", "урок", "тема"],
    "FR": ["chapitre", "leçon", "cours", "section", "partie"],
    "EN": ["lecture", "chapter", "lesson", "section", "unit"],
    "ID": ["bab", "pelajaran", "ceramah", "bagian", "unit"],
}

# Scoring weights for each category signal.
_SCORING_WEIGHTS: dict[str, float] = {
    "exam_choices": 3.0,
    "exam_checkboxes": 2.5,
    "code_block": 2.0,
    "book_length": 1.5,
    "book_headings": 1.5,
    "lecture_length": 1.0,
    "lecture_lists": 1.0,
    "lecture_keywords": 1.5,
    "short_length": 2.0,
    "table_ratio": 1.5,
}

# Minimum score to win a category.
_SCORING_THRESHOLD = 2.0


def classify_file_scoring(meta: dict, content: str, primary_lang: str = "") -> str:
    """Classify a file using weighted scoring with language-aware keywords.

    Each signal contributes a weighted score. The category with the highest
    total score wins, provided it exceeds _SCORING_THRESHOLD. Falls back to
    the priority-match classifier if no category reaches threshold.

    Args:
        meta: Dict with keys 'line_count' (int) and 'table_ratio' (float).
        content: The full file content as a string.
        primary_lang: Expected language code (AR/RU/FR/EN/ID).

    Returns:
        One of: 'exam', 'tutorial', 'book', 'lecture', 'short', 'table', 'misc'.
    """
    line_count: int = meta.get("line_count", 0)
    scores: dict[str, float] = {}

    # Exam signals
    choice_count = len(_RE_EXAM_CHOICE.findall(content))
    checkbox_count = len(_RE_EXAM_CHECKBOX.findall(content))
    if choice_count >= 5:
        scores["exam"] = scores.get("exam", 0) + _SCORING_WEIGHTS["exam_choices"]
    if checkbox_count >= 3:
        scores["exam"] = scores.get("exam", 0) + _SCORING_WEIGHTS["exam_checkboxes"]

    # Tutorial signal
    if _has_code_block(content):
        scores["tutorial"] = scores.get("tutorial", 0) + _SCORING_WEIGHTS["code_block"]

    # Book signals
    if line_count > 500:
        scores["book"] = scores.get("book", 0) + _SCORING_WEIGHTS["book_length"]
    has_h1 = bool(_RE_H1.search(content))
    has_h2 = bool(_RE_H2.search(content))
    has_h3 = bool(_RE_H3.search(content))
    heading_depth = sum([has_h1, has_h2, has_h3])
    if heading_depth >= 3:
        scores["book"] = scores.get("book", 0) + _SCORING_WEIGHTS["book_headings"]

    # Lecture signals
    if 100 <= line_count <= 500:
        scores["lecture"] = scores.get("lecture", 0) + _SCORING_WEIGHTS["lecture_length"]
    lines = content.split("\n")
    if lines:
        list_lines = sum(1 for line in lines if _RE_LIST_MARKER.match(line))
        if (list_lines / len(lines)) > 0.10:
            scores["lecture"] = scores.get("lecture", 0) + _SCORING_WEIGHTS["lecture_lists"]
    # Language-aware lecture keywords
    lang_keywords = _LECTURE_KEYWORDS.get(primary_lang, [])
    if lang_keywords:
        for kw in lang_keywords:
            if kw in content:
                scores["lecture"] = scores.get("lecture", 0) + _SCORING_WEIGHTS["lecture_keywords"]
                break

    # Short signal
    if line_count < 100:
        scores["short"] = scores.get("short", 0) + _SCORING_WEIGHTS["short_length"]

    # Table signal
    table_ratio: float = meta.get("table_ratio", 0.0)
    if table_ratio > 0.70:
        scores["table"] = scores.get("table", 0) + _SCORING_WEIGHTS["table_ratio"]

    # Pick the highest-scoring category above threshold.
    if scores:
        best_category = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best_category] >= _SCORING_THRESHOLD:
            return best_category

    # Fallback to priority-match classifier.
    return classify_file(meta, content)
