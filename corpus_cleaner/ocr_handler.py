"""OCR contamination handler — detects and cleans OCR noise.

Implements Stage 3 of the corpus cleaning pipeline:
- Per-line contaminant character scoring with CJK / embedded-Latin /
  garbled-sequence rules per primary language.
- Whitelist exemption via i18n_tokens.RE_WHITELIST.
- Code-block line exemption.
- 95th-percentile aggregation for robust file-level score.
- Four-level contaminant cleaning: flag-only, clean-mark, clean-light,
  clean-aggressive.
"""

from __future__ import annotations

import re

from corpus_cleaner.i18n_tokens import RE_WHITELIST
from corpus_cleaner.utils import read_file_auto

import json
from pathlib import Path
import math

# ══════════════════════════════════════════════════════════════════════════════
# Unicode range constants
# ══════════════════════════════════════════════════════════════════════════════

# CJK Unified Ideographs (common), Extension A, Compatibility Ideographs.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
)

# Embedded-Latin detection patterns (Stage 3, plan Section 3).
# Arabic char + 1-3 Latin letters + Arabic char  → the Latin letters are OCR noise.
_RE_EMBEDDED_LATIN_AR: re.Pattern[str] = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF][A-Za-z]{1,3}"
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]"
)

# Cyrillic char + 1-3 Latin letters + Cyrillic char.
_RE_EMBEDDED_LATIN_RU: re.Pattern[str] = re.compile(
    r"[\u0400-\u04FF][A-Za-z]{1,3}[\u0400-\u04FF]"
)

# Garbled sequences: ≥3 consecutive non-alphanumeric, non-French-letter,
# non-whitespace symbols.  French letters covered by Latin-1 Supplement
# (U+00C0-U+00FF: À-ÿ, includes àâäèéêëîïôöùûüÿç + uppercase).
_RE_GARBLED: re.Pattern[str] = re.compile(
    r"[^a-zA-Z0-9\u00C0-\u00FF\s]{3,}"
)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def compute_contamination(
    content: str,
    primary_lang: str,
    threshold: float = 0.05,
    whitelist: re.Pattern[str] | None = None,
) -> tuple[float, list[dict]]:
    """Compute OCR contamination score and per-line detail records.

    Algorithm per plan Stage 3:

    1. Mark code-block lines (exempt from contamination analysis).
    2. Strip whitelist patterns (URLs, emails, abbreviations, etc.) from
       every line — those are legitimate bilingual content.
    3. For each non-code-block, non-empty line:
       a. Find contaminant character positions:
          - CJK characters (all languages).
          - Embedded Latin 1-3 chars between Arabic/Cyrillic (AR / RU).
          - Garbled sequences ≥3 consecutive non-alnum symbols (FR).
       b. Compute ``fraction = contaminant_count / total_chars_in_line``.
    4. File-level score = 95th percentile of per-line fractions
       (robust to a few noisy lines).

    Args:
        content: Raw file content.
        primary_lang: Expected primary language (AR / RU / FR / EN).
        threshold: Per-line fraction above which a line is considered
                   contaminated in the detail list.  (Only affects the
                   ``above_threshold`` field; the score is always
                   computed regardless of threshold.)

    Returns:
        A tuple of ``(contamination_score, detail_list)``:
        - *contamination_score*: 95th-percentile per-line fraction (0.0–1.0).
        - *detail_list*: list of per-line dicts with keys ``line``,
          ``contaminant_chars``, ``total_chars``, ``fraction``,
          ``above_threshold``.

    """
    # 1. Mark code-block lines → entirely exempt.
    code_lines: set[int] = _mark_code_blocks(content)

    # 2. Strip whitelist patterns from the whole content.
    wl = whitelist if whitelist is not None else RE_WHITELIST
    cleaned: str = _strip_whitelist(content, wl)
    lines: list[str] = cleaned.split("\n")

    per_line_fractions: list[float] = []
    detail_list: list[dict] = []
    total_contaminant_chars: int = 0

    # Per-language contaminant detectors.
    embedded_latin_re: re.Pattern[str] | None = None
    garbled_re: re.Pattern[str] | None = None

    if primary_lang == "AR":
        embedded_latin_re = _RE_EMBEDDED_LATIN_AR
    elif primary_lang == "RU":
        embedded_latin_re = _RE_EMBEDDED_LATIN_RU
    elif primary_lang == "FR":
        garbled_re = _RE_GARBLED

    for line_idx, line in enumerate(lines):
        # Skip code-block lines (entirely exempt).
        if line_idx in code_lines:
            continue

        # Skip empty / whitespace-only lines.
        stripped = line.strip()
        if not stripped:
            continue

        total_chars: int = len(stripped)
        if total_chars == 0:
            continue

        # Collect unique contaminant character positions (set avoids
        # double-counting when a char matches multiple rules).
        contaminant_positions: set[int] = set()

        # a. CJK characters (all languages).
        for pos, ch in enumerate(stripped):
            if _is_contaminant_char(ch, primary_lang):
                contaminant_positions.add(pos)

        # b. Embedded Latin patterns (AR / RU).
        if embedded_latin_re is not None:
            for match in embedded_latin_re.finditer(stripped):
                for j, ch in enumerate(match.group()):
                    if ch.isascii() and ch.isalpha():
                        contaminant_positions.add(match.start() + j)

        # c. Garbled sequences (FR).
        if garbled_re is not None:
            for match in garbled_re.finditer(stripped):
                for j in range(match.start(), match.end()):
                    contaminant_positions.add(j)

        contaminant_count: int = len(contaminant_positions)
        total_contaminant_chars += contaminant_count
        fraction: float = contaminant_count / total_chars

        per_line_fractions.append(fraction)
        detail_list.append(
            {
                "line": line_idx,
                "contaminant_chars": contaminant_count,
                "total_chars": total_chars,
                "fraction": fraction,
                "above_threshold": fraction > threshold,
            }
        )

    # 4. 95th-percentile score.
    if not per_line_fractions:
        score = 0.0
    else:
        sorted_fractions = sorted(per_line_fractions)
        # Index at 95% position; clamp to valid range.
        pct_idx = max(0, int(0.95 * len(sorted_fractions)) - 1)
        score = sorted_fractions[pct_idx]

    # Sparse contamination floor: files with a significant absolute count
    # of contaminant characters should be flagged even when the 95th
    # percentile is diluted across many mostly-clean lines.
    if total_contaminant_chars >= 50 and score < threshold:
        score = threshold

    return (score, detail_list)


# ══════════════════════════════════════════════════════════════════════════════
# Private helpers
# ══════════════════════════════════════════════════════════════════════════════


def _is_cjk(char: str) -> bool:
    """Return True if *char* is in a CJK Unicode block."""
    cp: int = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_contaminant_char(char: str, primary_lang: str) -> bool:
    """Determine whether a single character is a contaminant for *primary_lang*.

    Per the plan, CJK characters are contaminants in all five supported
    languages.  Embedded-Latin and garbled-sequence patterns require
    multi-character context and are handled at the line level by
    ``compute_contamination``, not here.
    """
    return _is_cjk(char)


def _strip_whitelist(text: str, pattern: re.Pattern[str] | None = None) -> str:
    """Remove whitelist-matched spans, replacing each with spaces.

    Preserves string length and character positions so that contaminant
    position tracking remains accurate after stripping.
    """
    wl = pattern if pattern is not None else RE_WHITELIST
    return wl.sub(lambda m: " " * len(m.group()), text)


def _mark_code_blocks(text: str) -> set[int]:
    """Return the set of 0-based line indices inside ``` code blocks.

    Lines inside fenced code blocks are entirely exempt from contamination
    analysis (they may legitimately contain any character set).
    The fence lines themselves are also exempt.
    """
    code_lines: set[int] = set()
    in_block: bool = False

    for i, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            code_lines.add(i)
        elif in_block:
            code_lines.add(i)

    return code_lines


def clean_content(
    content: str,
    primary_lang: str,
    mode: str = "flag-only",
    whitelist: re.Pattern[str] | None = None,
) -> tuple[str, list[dict]]:
    """Clean OCR contamination from content based on the specified mode.

    Four modes per plan Stage 3:

    - **flag-only**: Return content unchanged.  Changes list is empty.
      Detection is handled by ``compute_contamination``.
    - **clean-mark**: Replace contaminant fragments with ``[?]`` placeholder.
      Consecutive contaminants are grouped into a single ``[?]``.
      Preserves complete syntax structure (safe).
    - **clean-light**: Delete independent contaminant fragments (surrounded
      by whitespace/punctuation on both sides).  Embedded fragments
      (adjacent to word characters) are replaced with ``[?]``.
    - **clean-aggressive**: Delete all contaminant characters.  May break
      semantics (dangling conjunctions, word-meaning changes).

    Whitelist-matched text (URLs, emails, abbreviations, etc.) and code
    block content are exempt from cleaning — they are left unchanged.

    Args:
        content: Raw file content.
        primary_lang: Expected primary language (AR / RU / FR / EN).
        mode: Cleaning mode — one of ``flag-only``, ``clean-mark``,
            ``clean-light``, ``clean-aggressive``.

    Returns:
        A tuple ``(cleaned_content, changes_list)``.
        Each change entry is a dict with keys ``position`` (int — 0-based
        absolute character index in original content), ``original`` (str),
        ``replacement`` (str), ``mode`` (str).
    """
    if mode == "flag-only":
        return (content, [])

    if mode not in ("clean-mark", "clean-light", "clean-aggressive"):
        raise ValueError(
            f"Unknown mode: {mode!r}. "
            f"Expected one of: flag-only, clean-mark, clean-light, clean-aggressive"
        )

    embedded_latin_re: re.Pattern[str] | None = None
    garbled_re: re.Pattern[str] | None = None
    if primary_lang == "AR":
        embedded_latin_re = _RE_EMBEDDED_LATIN_AR
    elif primary_lang == "RU":
        embedded_latin_re = _RE_EMBEDDED_LATIN_RU
    elif primary_lang == "FR":
        garbled_re = _RE_GARBLED

    code_lines: set[int] = _mark_code_blocks(content)
    wl = whitelist if whitelist is not None else RE_WHITELIST
    stripped_content: str = _strip_whitelist(content, wl)
    lines: list[str] = stripped_content.split("\n")
    original_lines: list[str] = content.split("\n")

    changes: list[dict] = []
    result_lines: list[str] = list(original_lines)
    abs_pos: int = 0

    for line_idx in range(len(lines)):
        orig_line: str = original_lines[line_idx]
        stripped_line: str = lines[line_idx]

        if line_idx in code_lines:
            abs_pos += len(orig_line) + 1
            continue

        stripped_trimmed: str = stripped_line.strip()
        if not stripped_trimmed:
            abs_pos += len(orig_line) + 1
            continue

        lstrip_len: int = len(stripped_line) - len(stripped_line.lstrip())

        # ── Find contaminant positions (same logic as compute_contamination) ──
        positions: set[int] = set()

        # a. CJK characters (all languages).
        for pos, ch in enumerate(stripped_trimmed):
            if _is_contaminant_char(ch, primary_lang):
                positions.add(pos)

        # b. Embedded Latin patterns (AR / RU).
        if embedded_latin_re is not None:
            for match in embedded_latin_re.finditer(stripped_trimmed):
                for j, ch in enumerate(match.group()):
                    if ch.isascii() and ch.isalpha():
                        positions.add(match.start() + j)

        # c. Garbled sequences (FR).
        if garbled_re is not None:
            for match in garbled_re.finditer(stripped_trimmed):
                for j in range(match.start(), match.end()):
                    positions.add(j)

        if not positions:
            abs_pos += len(orig_line) + 1
            continue

        # ── Group consecutive positions into spans ──
        sorted_positions: list[int] = sorted(positions)
        spans: list[tuple[int, int]] = []
        span_start: int = sorted_positions[0]
        prev: int = sorted_positions[0]
        for p in sorted_positions[1:]:
            if p != prev + 1:
                spans.append((span_start, prev + 1))
                span_start = p
            prev = p
        spans.append((span_start, prev + 1))

        # ── Apply mode-specific cleaning (right-to-left preserves positions) ──
        for start, end in reversed(spans):
            orig_start: int = lstrip_len + start
            orig_end: int = lstrip_len + end

            if orig_end <= len(orig_line):
                original_text: str = orig_line[orig_start:orig_end]
            else:
                original_text = stripped_trimmed[start:end]

            if mode == "clean-mark":
                replacement: str = "[?]"
            elif mode == "clean-light":
                if _is_independent_span(stripped_trimmed, start, end):
                    replacement = ""
                else:
                    replacement = "[?]"
            else:
                replacement = ""

            current: str = result_lines[line_idx]
            result_lines[line_idx] = (
                current[:orig_start] + replacement + current[orig_end:]
            )

            changes.append(
                {
                    "position": abs_pos + orig_start,
                    "original": original_text,
                    "replacement": replacement,
                    "mode": mode,
                }
            )

        if mode == "clean-aggressive":
            changes.append(
                {
                    "position": abs_pos,
                    "original": "",
                    "replacement": "",
                    "mode": mode,
                    "warning": (
                        "Aggressive deletion may break semantics "
                        "(dangling conjunctions, word-meaning changes)"
                    ),
                }
            )

        abs_pos += len(orig_line) + 1

    return ("\n".join(result_lines), changes)


def _is_independent_span(text: str, start: int, end: int) -> bool:
    """Check whether contaminant span [*start*, *end*) is surrounded by
    whitespace or punctuation on both sides.

    A span is *independent* (safe to delete) when both its left and right
    neighbours are word separators (whitespace or non-alphanumeric).
    Otherwise it is *embedded* — adjacent to word characters on at least
    one side.
    """
    left_ok: bool = start == 0 or not text[start - 1].isalnum()
    right_ok: bool = end >= len(text) or not text[end].isalnum()
    return left_ok and right_ok


# ── Same-script garbled text detection via KL divergence ──────────────────

_LANG_PROFILES_DIR = Path(__file__).parent / "lang_profiles"
_profile_cache: dict[str, dict[str, float]] = {}


def _load_lang_profile(lang: str) -> dict[str, float]:
    """Load character frequency profile for *lang* from lang_profiles/{lang}.json."""
    if lang in _profile_cache:
        return _profile_cache[lang]
    profile_path = _LANG_PROFILES_DIR / f"{lang}.json"
    if not profile_path.exists():
        return {}
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    _profile_cache[lang] = data
    return data


def compute_char_freq_kl(
    content: str,
    primary_lang: str,
    threshold: float = 2.0,
) -> float:
    """Compute KL divergence between content char frequency and reference profile.

    High KL divergence indicates the content's character distribution is
    anomalous for the expected language — a signal of same-script garbled text
    (e.g., OCR artifacts that are valid Arabic/Cyrillic characters but
    statistically unusual).

    Args:
        content: Raw file content.
        primary_lang: Expected primary language (AR/RU/FR/EN/ID).
        threshold: KL divergence above which content is considered garbled.

    Returns:
        KL divergence score (0.0 if profile unavailable or content empty).
    """
    if not content or not content.strip():
        return 0.0

    ref_profile = _load_lang_profile(primary_lang)
    if not ref_profile:
        return 0.0

    # Compute observed character frequencies (lowercase, alpha only).
    char_counts: dict[str, int] = {}
    total = 0
    for ch in content:
        if ch.isalpha():
            key = ch.lower()
            char_counts[key] = char_counts.get(key, 0) + 1
            total += 1

    if total == 0:
        return 0.0

    # Compute KL divergence: sum(obs * log(obs / ref))
    # Use smoothing: add epsilon to avoid log(0).
    epsilon = 1e-6
    kl = 0.0
    for ch, count in char_counts.items():
        obs = count / total
        ref = ref_profile.get(ch, epsilon)
        if ref > 0:
            kl += obs * math.log(obs / ref)

    return kl
