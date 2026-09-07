"""Table file filter — identifies files dominated by HTML tables.

Functions:
- is_table_file(meta, content, threshold) → bool
- is_empty_file(meta) → bool
- is_bad_file(meta) → bool
- classify_file_status(meta, content, threshold) → str
"""

from __future__ import annotations

import re

_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_RE_MD_LINK = re.compile(r"\[[^\]]*\]\([^)]+\)")
_RE_CODE_FENCE = re.compile(r"```[\s\S]*?```")


def is_table_file(meta: dict, content: str, threshold: float = 0.70) -> bool:
    """Return True if the file's table_ratio exceeds the threshold.

    Uses strictly-greater comparison: ratio exactly at threshold is NOT a table file.
    The table_ratio is computed by the scanner as: lines containing <table> / total lines.

    Args:
        meta: File metadata dict with at least 'table_ratio' key.
        content: Raw file content (reserved for future single-line validation).
        threshold: Ratio above which the file is considered table-dominant.
    """
    ratio = meta.get("table_ratio", 0)
    return ratio > threshold


def is_empty_file(meta: dict) -> bool:
    """Return True if the file has zero lines.

    Args:
        meta: File metadata dict with at least 'line_count' key.
    """
    return meta.get("line_count", 0) == 0


def is_bad_file(meta: dict) -> bool:
    """Return True if the file is unreadable or binary.

    Args:
        meta: File metadata dict; checks for 'status' == 'bad'.
    """
    return meta.get("status") == "bad"


def classify_file_status(
    meta: dict, content: str, threshold: float = 0.70
) -> str:
    """Classify a file into one of six statuses.

    Priority order: bad -> empty -> table -> html_noisy -> image_only -> ok.

    Returns one of: "bad", "empty", "image_only", "table", "html_noisy", "ok".
    """
    if is_bad_file(meta):
        return "bad"
    if is_empty_file(meta):
        return "empty"
    if is_table_file(meta, content, threshold):
        return "table"
    if is_image_only(content, min_chars=50):
        return "image_only"
    if is_html_noisy(content, threshold=0.40):
        return "html_noisy"
    return "ok"


def is_html_noisy(content: str, threshold: float = 0.40) -> bool:
    """Return True if HTML tag characters exceed *threshold* of total content.

    Detects files where HTML markup dominates but <table> density may be low
    (e.g., navigation-heavy scraped pages).
    """
    if not content or not content.strip():
        return False
    tag_chars = sum(len(m.group()) for m in _RE_HTML_TAG.finditer(content))
    total = len(content)
    if total == 0:
        return False
    return (tag_chars / total) > threshold


def is_image_only(content: str, min_chars: int = 100) -> bool:
    """Return True if the file has negligible text after stripping images/links.

    Files that are mostly image references with little or no prose text
    have no retrieval value and should be isolated.
    """
    if not content:
        return True
    # Strip images, links, code fences, then count remaining non-whitespace chars.
    text = _RE_MD_IMAGE.sub("", content)
    text = _RE_MD_LINK.sub("", text)
    text = _RE_CODE_FENCE.sub("", text)
    # Do NOT strip HTML tags here - is_html_noisy handles that.
    # Count non-whitespace characters.
    net_chars = sum(1 for ch in text if not ch.isspace())
    return net_chars < min_chars


# ══════════════════════════════════════════════════════════════════════════════
# trafilatura HTML extraction (thorough profile only)
# ══════════════════════════════════════════════════════════════════════════════


def extract_html_content(content: str) -> str | None:
    """Extract main text from HTML-heavy content using trafilatura.

    Returns None if trafilatura is not installed or extraction fails.
    Only used in thorough profile for table/html_noisy rescue.

    Args:
        content: Raw file content (may contain HTML).

    Returns:
        Extracted clean text, or None on failure.
    """
    try:
        import trafilatura
    except ImportError:
        return None

    if not content or not content.strip():
        return None

    # trafilatura works on HTML; if content doesn't look like HTML, skip.
    if "<" not in content or ">" not in content:
        return None

    try:
        result = trafilatura.extract(content)
        if result and len(result.strip()) > 50:
            return result
    except Exception:
        pass

    return None
