"""File renamer — generates semantic filenames from content.

Functions:
- _extract_title(content) → str — extract title with 4-priority fallback
- _sanitize(title) → str — clean title for filename, preserve Unicode
- _compute_length_bracket(net_char_count, thresholds) → str — S/M/L
- generate_new_name(meta, content, category, seq, thresholds) → str

Naming convention: {category}_{topic}_{seq:03d}_{S|M|L}.md
"""

from __future__ import annotations

import re

from corpus_cleaner.config import PipelineConfig

# Windows forbidden filename characters: \ / : * ? " < > |
_RE_FORBIDDEN = re.compile(r'[\\/:*?"<>|]+')
_RE_WHITESPACE = re.compile(r"\s+")
_RE_H1 = re.compile(r"^#\s+(.*)")
_RE_H2 = re.compile(r"^##\s+(.*)")
_RE_MD_IMG = re.compile(r"!\[.*?\]\(.*?\)")
_RE_HTML_START = re.compile(r"^\s*<")

# Only Latin letters (a-z, A-Z) are lowercased; Unicode (Arabic, Cyrillic, CJK) preserved.
_RE_LATIN = re.compile(r"[A-Za-z]+")

_MAX_TOPIC_CHARS = 50


def _extract_title(content: str) -> str:
    """Extract a title from markdown content with 4-priority fallback.

    Priority order:
    1. First non-empty # heading (h1)
    2. First non-empty ## heading (h2)
    3. First non-empty, non-HTML, non-image line in first 20 lines
    4. Fallback: "untitled"

    Args:
        content: The raw markdown content of the file.

    Returns:
        The extracted title string (not yet sanitized for filename use).
    """
    if not content:
        return "untitled"

    lines = content.splitlines()

    for line in lines:
        m = _RE_H1.match(line)
        if m and m.group(1).strip():
            return m.group(1).strip()

    for line in lines:
        m = _RE_H2.match(line)
        if m and m.group(1).strip():
            return m.group(1).strip()

    for line in lines[:20]:
        stripped = line.strip()
        if not stripped:
            continue
        if _RE_HTML_START.match(stripped):
            continue
        if _RE_MD_IMG.search(stripped):
            continue
        cleaned = _RE_MD_IMG.sub("", stripped).strip()
        if cleaned:
            return cleaned

    return "untitled"


def _sanitize(title: str) -> str:
    """Clean a title for use in a filename, preserving Unicode characters.

    Steps:
    0. Strip C0 control characters (U+0000-U+001F) except tab, newline, carriage return.
    1. Replace Windows forbidden characters (\\ / : * ? \" < > |) with '_'.
    2. Collapse consecutive whitespace (including newlines) to '_'.
    3. Lowercase Latin letters (a-z, A-Z) only — Arabic, Cyrillic, CJK have no case.
    4. Truncate to 50 characters.
    5. Strip leading/trailing underscores.
    6. If empty after all steps, return 'untitled'.

    Args:
        title: Raw title string from _extract_title().

    Returns:
        A sanitized string safe for Windows filenames, with Unicode preserved.
    """
    # Strip C0 control chars (null bytes, etc.) — these crash openpyxl in filenames.
    result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", title)
    result = _RE_FORBIDDEN.sub("_", result)
    result = _RE_WHITESPACE.sub("_", result)
    result = _RE_LATIN.sub(lambda m: m.group(0).lower(), result)

    if len(result) > _MAX_TOPIC_CHARS:
        result = result[:_MAX_TOPIC_CHARS]

    result = result.strip("_")

    if not result:
        result = "untitled"

    return result


def _compute_length_bracket(
    net_char_count: int, thresholds: tuple[int, int]
) -> str:
    """Compute the size bracket (S/M/L) from net character count.

    Args:
        net_char_count: The net character count (markdown/HTML noise stripped).
        thresholds: A tuple of (S/M boundary, M/L boundary), e.g. (20000, 50000).

    Returns:
        'S' if net_char_count <= thresholds[0],
        'M' if thresholds[0] < net_char_count <= thresholds[1],
        'L' if net_char_count > thresholds[1].
    """
    sm_boundary, ml_boundary = thresholds
    if net_char_count <= sm_boundary:
        return "S"
    if net_char_count <= ml_boundary:
        return "M"
    return "L"


def generate_new_name(
    meta: dict,
    content: str,
    category: str,
    seq: int,
    thresholds: tuple[int, int] = (20000, 50000),
    *,
    domain: str = "",
    topic: str = "",
) -> str:
    """Generate a semantic filename for a cleaned corpus file.

    Format (without domain):  {category}_{topic}_{seq:03d}_{length_bracket}.md
    Format (with domain):     {category}_{domain}_{topic}_{seq:03d}_{length_bracket}.md

    When ``domain`` and ``topic`` are provided (e.g., from LLM renaming), they
    are used directly instead of extracting the title from content.  ``domain``
    is the academic field (e.g., 'biology', 'physics') and ``topic`` is the
    semantic subject (e.g., 'dna_replication').  Both are sanitized.

    When ``domain`` is empty, the legacy format ``{category}_{topic}_...`` is
    used (backward compatible).

    The length bracket is taken from meta['length_bracket'] if present,
    otherwise computed from meta['net_char_count'].

    Args:
        meta: File metadata dict (must contain 'net_char_count' or 'length_bracket').
        content: The raw markdown/text content of the file.
        category: The category string (exam/tutorial/book/lecture/short/table/misc).
        seq: The 1-based sequence number for this (folder, category) group.
        thresholds: (S/M boundary, M/L boundary) tuple. Default (20000, 50000).
        domain: Optional academic domain from LLM (e.g., 'biology').
        topic: Optional semantic topic from LLM (e.g., 'dna_replication').

    Returns:
        A filename string like 'book_biology_dna_replication_001_L.md'
        or 'book_basic_clinical_anesthesia_001_L.md' (legacy format).
    """
    if domain and topic:
        topic_sanitized = _sanitize(topic)
        domain_sanitized = _sanitize(domain)
        topic_str = f"{domain_sanitized}_{topic_sanitized}"
    elif topic:
        topic_str = _sanitize(topic)
    else:
        title = _extract_title(content)
        topic_str = _sanitize(title)

    length_bracket = meta.get("length_bracket")
    if length_bracket is None:
        net_char_count = meta.get("net_char_count", 0)
        length_bracket = _compute_length_bracket(net_char_count, thresholds)

    return f"{category}_{topic_str}_{seq:03d}_{length_bracket}.md"
