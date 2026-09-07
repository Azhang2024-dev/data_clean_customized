"""File scanner — discovers and parses corpus files.

Implements Stage 1 of the corpus cleaning pipeline:
- Filename parsing via standard naming convention
- Recursive file discovery with auto-detection of language folders
- Metadata extraction (line count, table ratio, language detection, net char count)
- Multi-part file recognition and merging
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fast_langdetect import detect

from corpus_cleaner.config import PipelineConfig
from corpus_cleaner.utils import md5_file, read_file_auto

# Deterministic language detection across runs.
# fast-langdetect uses fastText models — deterministic by default.

# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

_FILENAME_PATTERN = re.compile(
    r"^(.+)_(\d{8,14})(?:_(\d{6}))?_(\d+)_([a-zA-Z0-9]{6,})(?:_(\d+))?(?:_(?:part)?(\d+))?\.(md|txt)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Net character count — noise stripping patterns
# Order matters: destructive patterns run before substitution patterns.
# ---------------------------------------------------------------------------

_RE_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_RE_TABLE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_RE_CODE_FENCE = re.compile(r"```(?:\w+)?\n([\s\S]*?)```")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_EMPHASIS = re.compile(r"\*{1,3}([^*]+?)\*{1,3}")
_RE_NUMBERED_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_RE_BULLET_LIST = re.compile(r"^\s*[-•]\s+", re.MULTILINE)
_RE_MULTI_WS = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Language mapping from folder name
# ---------------------------------------------------------------------------

_LANG_KEYWORDS: list[tuple[str, str]] = [
    ("阿语", "AR"),
    ("俄语", "RU"),
    ("法语", "FR"),
    ("印尼语", "ID"),
]


# Direct folder name → language code mapping (for pre-segmented folders).
_DIRECT_LANG: dict[str, str] = {
    "FR": "FR", "AR": "AR", "RU": "RU", "ID": "ID", "EN": "EN",
}

# langdetect output (ISO 639-1) → our language codes.
_LANG_DETECT_MAP: dict[str, str] = {
    "ar": "AR", "ru": "RU", "fr": "FR", "en": "EN", "id": "ID",
}


def _extract_primary_lang(folder_name: str, lang_map: dict[str, str] | None = None) -> str:
    """Map a folder name to its primary language code.

    Handles both ``用户回流{lang}*`` pattern folders and direct language
    codes (``FR``, ``AR``, ``RU``, etc.).

    >>> _extract_primary_lang("用户回流阿语筛选")
    'AR'
    >>> _extract_primary_lang("用户回流印尼语300篇")
    'ID'
    >>> _extract_primary_lang("用户回流EN多格式")
    'EN'
    >>> _extract_primary_lang("FR")
    'FR'
    """
    # Check lang_map override first.
    if lang_map and folder_name in lang_map:
        return lang_map[folder_name]
    # Check direct code first (e.g. "FR", "AR").
    if folder_name in _DIRECT_LANG:
        return _DIRECT_LANG[folder_name]
    # Then check keyword patterns (e.g. "用户回流法语...").
    for keyword, code in _LANG_KEYWORDS:
        if keyword in folder_name:
            return code
    if "EN" in folder_name.upper():
        return "EN"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# FileMeta dataclass
# ---------------------------------------------------------------------------


@dataclass
class FileMeta:
    """Metadata for a single corpus file or a merged multi-part group.

    All fields are populated during Stage 1 (scanning).  ``contamination_score``
    defaults to 0.0 and is filled in by Stage 3 (OCR handler).  ``content`` is
    optional — downstream stages may discard it to save memory.
    """

    file_id: str
    """Unique identifier derived from the filename prefix + timestamp + seq."""

    timestamp: str
    """Timestamp component extracted from the filename (empty for non-standard names)."""

    hash: str
    """Hash component from the filename — identical across multi-part splits."""

    part: int
    """Part number extracted from the filename suffix (0 for single files)."""

    path: Path
    """Absolute path to the first part file on disk."""

    source_folder: str
    """Name of the input subfolder this file was discovered in."""

    primary_lang: str
    """Expected primary language derived from the folder name (AR/RU/FR/EN/UNKNOWN)."""

    detected_lang: str
    """Language detected by langdetect on the first 500 characters ('error' on failure)."""

    line_count: int
    """Total number of lines in the file (-1 for unreadable files)."""

    table_ratio: float
    """Fraction of non-empty lines that contain '<table' (case-insensitive)."""

    first_h1: str
    """Text of the first level-1 markdown heading ('# Title'), empty if none."""

    raw_char_count: int
    """Total character count of the raw file content (-1 for unreadable files)."""

    net_char_count: int
    """Character count after stripping markdown/HTML noise (-1 for unreadable files)."""

    length_bracket: str
    """Size bracket derived from net_char_count: 'S', 'M', or 'L'."""

    contamination_score: float = 0.0
    """OCR contamination score (populated by Stage 3)."""

    content: str | None = None
    """Full file content, or combined content for merged multi-part files."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_files(config: PipelineConfig) -> list[FileMeta]:
    """Scan input directories and return metadata for all discoverable files.

    Auto-discovers ``用户回流*`` subdirectories when ``config.folders`` is
    empty.  Recursively collects ``.md`` and ``.txt`` files, extracts metadata
    for each, then groups and merges multi-part files (same *file_id* and
    *hash* from filename, different ``_partNNN`` suffix).
    """
    input_path = Path(config.input_path)

    # --- resolve folders ---------------------------------------------------
    if config.folders:
        folder_paths = [input_path / f for f in config.folders]
    else:
        folder_glob = config.folder_glob
        folder_paths = sorted(input_path.glob(folder_glob))


    # Fallback: if no subdirectories matched, treat input_path itself as a folder.
    # This handles flat directories (e.g. Wikipedia extractions) with no 用户回流* structure.
    if not folder_paths:
        folder_paths = [input_path]

    # --- scan every folder -------------------------------------------------
    all_files: list[FileMeta] = []

    for folder in folder_paths:
        if not folder.is_dir():
            continue
        primary_lang = _extract_primary_lang(folder.name, config.lang_map if config.lang_map else None)
        for ext in ("*.md", "*.txt"):
            for file_path in sorted(folder.rglob(ext)):
                meta = _extract_meta(file_path, folder.name, primary_lang, config)
                all_files.append(meta)

    # --- multi-part merge --------------------------------------------------
    return _merge_multi_part(all_files)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_filename(name: str) -> dict:
    """Parse a standard corpus filename into its components.

    Expected format:
        ``{prefix}_{timestamp}_{seq}_{hash}[_partNNN].{md|txt}``

    Returns:
        A dict with keys ``prefix``, ``timestamp``, ``seq``, ``hash``,
        ``part`` (int, 0 when absent), and ``ext``.  Returns an empty dict
        when the name does not match the convention.
    """
    m = _FILENAME_PATTERN.match(name)
    if not m:
        return {}
    return {
        "prefix": m.group(1),
        "timestamp": m.group(2),
        "seq": m.group(4),
        "hash": m.group(5),
        "part": int(m.group(7)) if m.group(7) else 0,
        "ext": m.group(8),
    }


def _extract_meta(
    path: Path, source_folder: str, primary_lang: str, config: PipelineConfig
) -> FileMeta:
    """Read a single file and extract all Stage-1 metadata.

    On read errors (binary file, permission denied, etc.) returns a ``FileMeta``
    with ``line_count = -1`` and ``detected_lang = "error"`` as sentinels.
    """
    # --- read file ---------------------------------------------------------
    try:
        content, _encoding = read_file_auto(path)
    except (OSError, UnicodeDecodeError, UnicodeError):
        return FileMeta(
            file_id=path.stem,
            timestamp="",
            hash="",
            part=0,
            path=path,
            source_folder=source_folder,
            primary_lang=primary_lang,
            detected_lang="error",
            line_count=-1,
            table_ratio=0.0,
            first_h1="",
            raw_char_count=-1,
            net_char_count=-1,
            length_bracket="",
            contamination_score=0.0,
            content=None,
        )

    # --- parse filename ----------------------------------------------------
    parsed = _parse_filename(path.name)
    if parsed:
        file_id = f"{parsed['prefix']}_{parsed['timestamp']}_{parsed['seq']}"
        timestamp = parsed["timestamp"]
        file_hash = parsed["hash"]
        part = parsed["part"]
    else:
        file_id = path.stem
        timestamp = ""
        file_hash = ""
        part = 0

    # --- compute metrics ---------------------------------------------------
    raw_char_count = len(content)
    line_count = len(content.splitlines())
    table_ratio = _compute_table_ratio(content)
    first_h1 = _extract_first_h1(content)
    net_char_count = _compute_net_char_count(content)
    length_bracket = _compute_length_bracket(net_char_count, config.length_thresholds)

    # --- language detection ------------------------------------------------
    if config.force_lang:
        detected_lang = config.force_lang
        if primary_lang == "UNKNOWN":
            primary_lang = config.force_lang
    else:
        try:
            sample = content[:500]
            raw_result = detect(sample) if sample.strip() else "unknown"
        except Exception:
            raw_result = "unknown"

        # fast-langdetect returns list[dict] e.g. [{"lang":"en","score":0.99}]
        # Extract top-1 language code as a string.
        if isinstance(raw_result, list) and raw_result:
            top = raw_result[0]
            detected_lang = top.get("lang", "unknown") if isinstance(top, dict) else str(top)
        else:
            detected_lang = str(raw_result)

        # Fallback: when folder-derived primary_lang is UNKNOWN, use content-detected language.
        if primary_lang == "UNKNOWN" and detected_lang in _LANG_DETECT_MAP:
            primary_lang = _LANG_DETECT_MAP[detected_lang]
            primary_lang = _LANG_DETECT_MAP[detected_lang]

    return FileMeta(
        file_id=file_id,
        timestamp=timestamp,
        hash=file_hash,
        part=part,
        path=path,
        source_folder=source_folder,
        primary_lang=primary_lang,
        detected_lang=detected_lang,
        line_count=line_count,
        table_ratio=table_ratio,
        first_h1=first_h1,
        raw_char_count=raw_char_count,
        net_char_count=net_char_count,
        length_bracket=length_bracket,
        contamination_score=0.0,
        content=content,
    )


def _compute_net_char_count(text: str) -> int:
    """Strip markdown and HTML noise, returning the net character count.

    Noise removed (see plan Section 3 Stage 1 净字符口径):
    1. Markdown images ``![alt](url)`` — removed entirely
    2. Entire ``<table>...</table>`` structures
    3. HTML tags ``<tag>``
    4. Markdown links ``[text](url)`` — keep *text*, drop ``(url)``
    5. Code-block fences ``` ``` `` — keep content, drop fences
    6. Heading prefixes ``#``, ``##``, ``###`` ...
    7. Bold/italic markers ``**``, ``*``
    8. Numbered-list markers ``1.``, ``2.`` ...
    9. Bullet-list markers ``-``, ``•``
    10. Collapse consecutive whitespace to a single space
    """
    text = _RE_MD_IMAGE.sub("", text)
    text = _RE_TABLE.sub("", text)
    text = _RE_HTML_TAG.sub("", text)
    text = _RE_MD_LINK.sub(r"\1", text)
    text = _RE_CODE_FENCE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_EMPHASIS.sub(r"\1", text)
    text = _RE_NUMBERED_LIST.sub("", text)
    text = _RE_BULLET_LIST.sub("", text)
    text = _RE_MULTI_WS.sub(" ", text)
    return len(text.strip())


def _compute_length_bracket(net_char_count: int, thresholds: tuple[int, int]) -> str:
    """Map a net character count to a size bracket.

    Default thresholds (20000, 50000):
        ≤ 20,000  → ``"S"``
        20,001–50,000 → ``"M"``
        > 50,000  → ``"L"``
    """
    s_boundary, m_boundary = thresholds
    if net_char_count <= s_boundary:
        return "S"
    if net_char_count <= m_boundary:
        return "M"
    return "L"


def _compute_table_ratio(text: str) -> float:
    """Return the fraction of non-empty lines that contain ``<table`` (case-insensitive),
    or the proportion of characters inside ``<table>...</table>`` tags — whichever is higher.

    Handles minified HTML where an entire table sits on a single line.
    Empty input → 0.0.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0

    table_lines = sum(1 for line in lines if "<table" in line.lower())
    line_ratio = table_lines / len(lines)

    total_len = len(text)
    if total_len == 0:
        return line_ratio
    table_matches = _RE_TABLE.findall(text)
    char_ratio = sum(len(m) for m in table_matches) / total_len

    return max(line_ratio, char_ratio)


def _extract_first_h1(text: str) -> str:
    """Return the text of the first ``# Title`` heading, or ``""``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return ""


def _merge_multi_part(files: list[FileMeta]) -> list[FileMeta]:
    """Group multi-part files by (file_id, hash) and merge them.

    Files sharing the same *file_id* and filename *hash* but differing
    ``_partNNN`` suffixes are merged into a single ``FileMeta`` with
    concatenated content, the latest timestamp, and ``part=0``.
    """
    # Separate singles from multi-part candidates.
    groups: dict[tuple[str, str], list[FileMeta]] = {}
    singles: list[FileMeta] = []

    for f in files:
        if f.part > 0:
            key = (f.file_id, f.hash)
            groups.setdefault(key, []).append(f)
        else:
            singles.append(f)

    # Merge each group.
    for (_file_id, _hash), parts in groups.items():
        if len(parts) == 1:
            singles.append(parts[0])
            continue

        parts.sort(key=lambda m: m.part)
        primary = parts[0]

        # Concatenate content with newline separation.
        combined_parts: list[str] = []
        for p in parts:
            if p.content:
                combined_parts.append(p.content)
        combined_content = "\n".join(combined_parts)

        # Pick the latest timestamp.
        timestamps = [p.timestamp for p in parts if p.timestamp]
        latest_ts = max(timestamps) if timestamps else ""

        # Recompute metrics on the combined content.
        raw_char_count = len(combined_content)
        line_count = len(combined_content.splitlines())
        table_ratio = _compute_table_ratio(combined_content)
        net_char_count = _compute_net_char_count(combined_content)
        # Use default thresholds for merged files — the config is not
        # threaded through here because multi-part files are rare and the
        # bracket is advisory.
        length_bracket = _compute_length_bracket(net_char_count, (20000, 50000))

        merged = FileMeta(
            file_id=primary.file_id,
            timestamp=latest_ts,
            hash=primary.hash,
            part=0,
            path=primary.path,
            source_folder=primary.source_folder,
            primary_lang=primary.primary_lang,
            detected_lang=primary.detected_lang,
            line_count=line_count,
            table_ratio=table_ratio,
            first_h1=primary.first_h1,
            raw_char_count=raw_char_count,
            net_char_count=net_char_count,
            length_bracket=length_bracket,
            contamination_score=0.0,
            content=combined_content.strip() if combined_content else None,
        )
        singles.append(merged)

    return singles
