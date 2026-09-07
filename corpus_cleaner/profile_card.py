"""Profile card extractor — language-agnostic document profiling.

Extracts a compact structured summary ("profile card") from any UTF-8 document
without LLM calls.  The card is designed to be sent to an LLM for semantic
renaming, keeping token usage minimal (~300-500 tokens per file).

Works with: French, Arabic, Russian, English, Indonesian, and any other
UTF-8-encoded language.  Keyword extraction uses character n-grams which are
script-agnostic — no language-specific tokenizers required.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex patterns — compiled once at module level
# ---------------------------------------------------------------------------

_RE_HEADING = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)
_RE_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_HTML_TABLE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_RE_CODE_FENCE = re.compile(r"```(?:\w+)?\n([\s\S]*?)```")
_RE_URL = re.compile(r"https?://\S+")
_RE_EMAIL = re.compile(r"\S+@[a-zA-Z0-9._-]+\.[a-zA-Z]+")
_RE_MULTI_WS = re.compile(r"\s+")
_RE_OCR_GARBAGE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Character n-gram range for keyword extraction (script-agnostic).
_NGRAM_MIN = 3
_NGRAM_MAX = 5

# How many characters of clean leading text to extract.
_FIRST_TEXT_CHARS = 300

# Maximum profile card size in characters (safety cap for huge documents).
_MAX_CARD_CHARS = 3000


# ---------------------------------------------------------------------------
# ProfileCard dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProfileCard:
    """Compact structured summary of a document for LLM consumption.

    All fields are strings or simple types — safe to serialize as JSON for
    API calls.  No content field — only metadata.
    """

    file_id: str
    """Unique identifier (filename stem or parsed file_id)."""

    original_name: str
    """Original filename including extension."""

    category: str
    """Document category: exam | tutorial | book | lecture | short | table | misc."""

    headings: list[str] = field(default_factory=list)
    """All markdown headings (h1-h6) in order of appearance, stripped."""

    first_text: str = ""
    """First ~300 characters of substantive text (images/HTML/blank lines skipped)."""

    keywords: list[str] = field(default_factory=list)
    """Top 5-8 character n-gram keywords, language-agnostic."""

    size_bracket: str = ""
    """Size bracket: S (≤20K), M (20-50K), L (>50K)."""

    net_char_count: int = 0
    """Net character count (markdown/HTML noise stripped)."""

    ocr_contamination: float = 0.0
    """Fraction of OCR-garbage characters (0.0 = clean)."""

    table_ratio: float = 0.0
    """Fraction of lines containing <table> tags."""

    primary_lang: str = "UNKNOWN"
    """Expected language code from folder name (AR/RU/FR/EN/ID/...)."""

    def to_prompt_text(self, index: int) -> str:
        """Format this card as a compact text block for an LLM prompt.

        Args:
            index: 1-based index of this document in the batch.

        Returns:
            A compact text representation suitable for LLM consumption.
        """
        lines = [
            f"[{index}] ID: {self.file_id}",
            f"    Category: {self.category}  Size: {self.size_bracket}  Lang: {self.primary_lang}",
        ]
        if self.headings:
            h_str = " > ".join(self.headings[:5])
            lines.append(f"    Headings: {h_str}")
        if self.keywords:
            lines.append(f"    Keywords: {', '.join(self.keywords[:30])}")
        if self.first_text:
            lines.append(f"    Preview: {self.first_text[:200]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_profile_card(
    content: str,
    file_id: str = "",
    original_name: str = "",
    category: str = "misc",
    primary_lang: str = "UNKNOWN",
    size_bracket: str = "",
    net_char_count: int = 0,
    table_ratio: float = 0.0,
) -> ProfileCard:
    """Extract a ProfileCard from raw document content.

    This is the main entry point.  All text processing is language-agnostic —
    it works on any UTF-8 script (Latin, Arabic, Cyrillic, CJK, etc.).

    Args:
        content: Raw document text.
        file_id: Unique identifier for the file.
        original_name: Original filename with extension.
        category: Pre-classified document category.
        primary_lang: Expected language code (e.g., 'FR', 'AR', 'RU').
        size_bracket: Pre-computed size bracket ('S'/'M'/'L').
        net_char_count: Pre-computed net character count.
        table_ratio: Pre-computed table ratio.

    Returns:
        A ProfileCard ready for LLM consumption.
    """
    if not content:
        return ProfileCard(
            file_id=file_id,
            original_name=original_name,
            category=category,
            size_bracket=size_bracket or "S",
            net_char_count=0,
            primary_lang=primary_lang,
        )

    # --- headings -----------------------------------------------------------
    headings = _extract_headings(content)

    # --- first substantive text ---------------------------------------------
    first_text = _extract_first_text(content)

    # --- keywords (character n-gram based, language-agnostic) ----------------
    keywords = _extract_keywords(content)

    # --- OCR contamination --------------------------------------------------
    ocr_contamination = _compute_ocr_contamination(content)

    return ProfileCard(
        file_id=file_id,
        original_name=original_name,
        category=category,
        headings=headings,
        first_text=first_text,
        keywords=keywords,
        size_bracket=size_bracket,
        net_char_count=net_char_count,
        ocr_contamination=ocr_contamination,
        table_ratio=table_ratio,
        primary_lang=primary_lang,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_headings(text: str) -> list[str]:
    """Extract all markdown headings (h1-h6) in document order.

    Args:
        text: Raw markdown content.

    Returns:
        List of heading texts (without # prefix), in order of appearance.
    """
    headings: list[str] = []
    for match in _RE_HEADING.finditer(text):
        heading_text = match.group(2).strip()
        if heading_text:
            headings.append(heading_text)
    return headings


def _extract_first_text(text: str, max_chars: int = _FIRST_TEXT_CHARS) -> str:
    """Extract the first substantive text from a document.

    Skips: blank lines, markdown images, HTML tags, URLs, code fences.
    Stops when accumulated text reaches max_chars.

    Args:
        text: Raw document content.
        max_chars: Maximum number of characters to extract.

    Returns:
        Cleaned leading text, truncated to max_chars.
    """
    # Strip noise globally first for clean line-by-line scanning.
    cleaned = _RE_MD_IMAGE.sub("", text)
    cleaned = _RE_HTML_TABLE.sub("", cleaned)
    cleaned = _RE_HTML_TAG.sub("", cleaned)
    cleaned = _RE_MD_LINK.sub(r"\1", cleaned)
    cleaned = _RE_CODE_FENCE.sub("", cleaned)
    cleaned = _RE_URL.sub("", cleaned)
    cleaned = _RE_EMAIL.sub("", cleaned)

    accumulated: list[str] = []
    char_count = 0

    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines that are just markdown syntax.
        if stripped.startswith(("#", "```", ">", "|", "- ", "* ", "1. ", "![", "<")):
            continue
        # Skip lines that are clearly not prose (too many special chars).
        alpha_ratio = sum(1 for c in stripped if c.isalpha() or c.isspace()) / max(len(stripped), 1)
        if alpha_ratio < 0.3 and len(stripped) > 20:
            continue
        # Collapse whitespace.
        clean_line = _RE_MULTI_WS.sub(" ", stripped)
        if char_count + len(clean_line) > max_chars:
            remaining = max_chars - char_count
            if remaining > 20:
                accumulated.append(clean_line[:remaining])
            break
        accumulated.append(clean_line)
        char_count += len(clean_line)

    result = " ".join(accumulated)
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


def _extract_keywords(text: str, top_n: int = 8) -> list[str]:
    """Extract top keywords using character n-grams (language-agnostic).

    Uses overlapping character n-grams (3-5 chars) which work identically
    for Latin, Arabic, Cyrillic, CJK, and any other script.  No tokenizer,
    no stopwords, no language model required.

    Args:
        text: Raw document content.
        top_n: Number of top keywords to return.

    Returns:
        List of top n-gram strings, sorted by frequency (descending).
    """
    # Clean text: remove URLs, emails, HTML, markdown images, code fences.
    cleaned = _RE_URL.sub(" ", text)
    cleaned = _RE_EMAIL.sub(" ", cleaned)
    cleaned = _RE_HTML_TABLE.sub(" ", cleaned)
    cleaned = _RE_HTML_TAG.sub(" ", cleaned)
    cleaned = _RE_MD_IMAGE.sub(" ", cleaned)
    cleaned = _RE_CODE_FENCE.sub(" ", cleaned)

    # Collapse whitespace.
    cleaned = _RE_MULTI_WS.sub(" ", cleaned).strip()
    if len(cleaned) < _NGRAM_MIN:
        return []

    # Extract overlapping character n-grams.
    ngram_counts: Counter[str] = Counter()
    for n in range(_NGRAM_MIN, _NGRAM_MAX + 1):
        for i in range(len(cleaned) - n + 1):
            ngram = cleaned[i : i + n]
            # Skip n-grams that are mostly whitespace or punctuation.
            if ngram.strip() and not _is_noise_ngram(ngram):
                ngram_counts[ngram] += 1

    # Filter: keep only n-grams appearing at least twice.
    # Return top_n by frequency.
    filtered = [(ng, cnt) for ng, cnt in ngram_counts.items() if cnt >= 2]
    filtered.sort(key=lambda x: (-x[1], x[0]))

    return [ng for ng, _ in filtered[:top_n]]


def _is_noise_ngram(ngram: str) -> bool:
    """Check if a character n-gram is mostly noise (punctuation, digits, whitespace).

    Args:
        ngram: A character n-gram string.

    Returns:
        True if the n-gram should be excluded from keywords.
    """
    alpha_or_script = sum(1 for c in ngram if c.isalpha() or _is_script_char(c))
    return alpha_or_script < len(ngram) * 0.5


def _is_script_char(c: str) -> bool:
    """Check if a character is part of a writing script (not punctuation/digit/space).

    This catches characters that Python's str.isalpha() misses for some scripts
    (e.g., Arabic diacritics, certain CJK punctuation-like chars that are
    actually script characters).
    """
    if c.isalpha():
        return True
    # Unicode categories that are script-adjacent:
    # Mn = Non-spacing mark (Arabic diacritics, etc.)
    # Mc = Spacing combining mark
    import unicodedata
    cat = unicodedata.category(c)
    return cat in ("Mn", "Mc")


def _compute_ocr_contamination(text: str) -> float:
    """Compute OCR contamination ratio.

    Counts C0 control characters and DEL as OCR garbage.  Returns a fraction
    of total characters.

    Args:
        text: Raw document content.

    Returns:
        Float between 0.0 (clean) and 1.0 (all garbage).
    """
    if not text:
        return 0.0
    garbage = len(_RE_OCR_GARBAGE.findall(text))
    return garbage / len(text)
