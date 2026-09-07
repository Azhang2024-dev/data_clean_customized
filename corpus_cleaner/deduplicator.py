"""Deduplicator — finds exact, suspected, and fuzzy duplicate files.

Exact dedup groups by MD5(content), keeping the latest timestamp.
Suspected dedup groups by (file_id, hash_from_name) prefix; same prefix
but different content → flagged as version differences (kept, not removed).
Fuzzy dedup (optional) uses min-hash Jaccard similarity on 3-word shingles.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from corpus_cleaner.utils import md5_file, read_file_auto

# 32-bit hash modulus for min-hash
_HASH_MOD = 2**32 - 1
_NUM_HASHES = 128
_SHINGLE_SIZE = 3
_FUZZY_THRESHOLD = 0.95
_SEED_PREFIXES: tuple[bytes, ...] = tuple(
    f"{i}:".encode("utf-8") for i in range(_NUM_HASHES)
)


@dataclass(frozen=True, slots=True)
class FileMeta:
    """Metadata for a single corpus file produced by scanner.

    Only the fields needed by the deduplicator are defined here.
    Additional fields may be added by scanner.py later.
    """

    path: Path
    """Absolute path to the file."""

    file_id: str = ""
    """Parsed file identifier from filename (e.g. '02h_20260610_014706_485')."""

    hash_from_name: str = ""
    """Hash component parsed from filename (e.g. 'CpvDEIJI')."""

    content_md5: str = ""
    """Pre-computed MD5 hex digest of file content. Computed on first use if empty."""

    timestamp: float = 0.0
    """File modification time as Unix timestamp (float)."""

    primary_lang: str = ""
    """Source language inferred from folder name (AR/RU/FR/EN)."""


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """A group of duplicate files found by the deduplicator."""

    kept: FileMeta
    """The file retained as the canonical copy (latest timestamp)."""

    duplicates: list[FileMeta]
    """Files identified as duplicates of `kept`."""

    reason: str
    """Why these files are considered duplicates: 'exact', 'suspected', or 'fuzzy'."""

    similarity: float
    """Similarity score: 1.0 for exact, -1.0 for suspected (content differs), Jaccard for fuzzy."""


def find_duplicates(
    file_list: list[FileMeta],
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.95,
) -> tuple[list[FileMeta], list[DuplicateGroup]]:
    """Find duplicate files by MD5 hash, filename prefix, and optionally fuzzy similarity.

    Processing order (matching Stage 4 of the plan):
    1. Exact dedup: group by MD5(content), keep latest timestamp.
    2. Suspected dedup: group by (file_id, hash_from_name); same prefix but
       different content → flag as version differences (ALL files kept).
    3. Fuzzy dedup (if enabled): min-hash Jaccard > 0.95 → mark as fuzzy dup,
       keep latest timestamp.

    Args:
        file_list: List of FileMeta objects from the scanner.
        fuzzy: If True, also run fuzzy (semantic) deduplication.
        fuzzy_threshold: Jaccard similarity threshold for fuzzy dedup (default 0.95).

    Returns:
        A tuple of (unique_files, duplicate_groups):
        - unique_files: files remaining after dedup (includes suspected).
        - duplicate_groups: groups of duplicates found, for the report.
    """
    if not file_list:
        return ([], [])

    # Ensure all files have content MD5 computed
    _ensure_md5(file_list)

    duplicate_groups: list[DuplicateGroup] = []

    # Phase 1: Exact dedup by content MD5
    unique_after_exact, exact_groups = _dedup_exact(file_list)
    duplicate_groups.extend(exact_groups)

    # Phase 2: Suspected dedup by (file_id, hash_from_name) prefix
    suspected_groups = _dedup_suspected(unique_after_exact)
    duplicate_groups.extend(suspected_groups)
    # All files are kept for suspected; unique_after_exact is unchanged

    # Phase 3: Fuzzy dedup (optional)
    unique_files: list[FileMeta]
    if fuzzy:
        unique_files, fuzzy_groups = _dedup_fuzzy(unique_after_exact, threshold=fuzzy_threshold)
        duplicate_groups.extend(fuzzy_groups)
    else:
        unique_files = unique_after_exact

    return (unique_files, duplicate_groups)


# ── Internal helpers ───────────────────────────────────────────────────────


def _ensure_md5(file_list: list[FileMeta]) -> None:
    """Compute content_md5 for any file that doesn't have it yet.

    FileMeta is frozen, so we mutate the list in place by replacing entries.
    """
    for i, meta in enumerate(file_list):
        if not meta.content_md5:
            new_md5 = md5_file(meta.path)
            # Replace with a new frozen instance that has the MD5 set
            file_list[i] = FileMeta(
                path=meta.path,
                file_id=meta.file_id,
                hash_from_name=meta.hash_from_name,
                content_md5=new_md5,
                timestamp=meta.timestamp,
                primary_lang=meta.primary_lang,
            )


def _dedup_exact(
    file_list: list[FileMeta],
) -> tuple[list[FileMeta], list[DuplicateGroup]]:
    """Group by content_md5; for groups with >1 file, keep the latest timestamp.

    Returns (unique_files, duplicate_groups).
    """
    by_md5: dict[str, list[FileMeta]] = defaultdict(list)
    for meta in file_list:
        by_md5[meta.content_md5].append(meta)

    unique_files: list[FileMeta] = []
    groups: list[DuplicateGroup] = []

    for md5_val, metas in by_md5.items():
        if len(metas) == 1:
            unique_files.append(metas[0])
            continue

        # Multiple files with same MD5 → exact duplicates
        sorted_metas = sorted(metas, key=lambda m: m.timestamp, reverse=True)
        kept = sorted_metas[0]
        dups = sorted_metas[1:]
        unique_files.append(kept)
        groups.append(
            DuplicateGroup(
                kept=kept,
                duplicates=dups,
                reason="exact",
                similarity=1.0,
            )
        )

    return (unique_files, groups)


def _dedup_suspected(
    file_list: list[FileMeta],
) -> list[DuplicateGroup]:
    """Group by (file_id, hash_from_name); same prefix but different MD5 → suspected.

    All files are kept in unique_files; only flagged for the report.
    Files without both file_id and hash_from_name are skipped.
    """
    by_prefix: dict[tuple[str, str], list[FileMeta]] = defaultdict(list)
    for meta in file_list:
        if meta.file_id and meta.hash_from_name:
            key = (meta.file_id, meta.hash_from_name)
            by_prefix[key].append(meta)

    groups: list[DuplicateGroup] = []
    for metas in by_prefix.values():
        if len(metas) <= 1:
            continue

        # Check if there are at least 2 distinct MD5 values in this group
        distinct_md5s = {m.content_md5 for m in metas}
        if len(distinct_md5s) <= 1:
            # All same MD5 → already handled by exact dedup
            continue

        # Same prefix, different content → suspected version difference
        sorted_metas = sorted(metas, key=lambda m: m.timestamp, reverse=True)
        groups.append(
            DuplicateGroup(
                kept=sorted_metas[0],
                duplicates=sorted_metas[1:],
                reason="suspected",
                similarity=-1.0,
            )
        )

    return groups


def _dedup_fuzzy(
    file_list: list[FileMeta],
    threshold: float = 0.95,
) -> tuple[list[FileMeta], list[DuplicateGroup]]:
    """Min-hash Jaccard similarity > threshold → fuzzy duplicate.

    Compares files within the same primary_lang only (cross-language
    comparisons are wasted work and could produce false positives).

    Returns (unique_files, fuzzy_groups).
    """
    if len(file_list) <= 1:
        return (list(file_list), [])

    # Group by primary_lang for efficient pairwise comparison
    by_lang: dict[str, list[FileMeta]] = defaultdict(list)
    for meta in file_list:
        by_lang[meta.primary_lang].append(meta)

    fuzzy_dups: set[int] = set()  # indices of files marked as fuzzy duplicates
    groups: list[DuplicateGroup] = []

    for metas in by_lang.values():
        if len(metas) <= 1:
            continue

        # Read content and compute min-hash signatures
        signatures: list[list[int] | None] = []
        for meta in metas:
            try:
                text, _enc = read_file_auto(meta.path)
            except (OSError, UnicodeDecodeError):
                signatures.append(None)
                continue
            tokens = _tokenize(text)
            sig = _minhash_signature(tokens, _NUM_HASHES)
            signatures.append(sig)

        # Pairwise comparison
        n = len(metas)
        for i in range(n):
            if signatures[i] is None:
                continue
            for j in range(i + 1, n):
                if signatures[j] is None:
                    continue
                jaccard = _jaccard_estimate(signatures[i], signatures[j])  # type: ignore[arg-type]
                if jaccard > threshold:
                    # Mark the one with earlier timestamp as duplicate
                    if metas[i].timestamp >= metas[j].timestamp:
                        kept, dup = metas[i], metas[j]
                    else:
                        kept, dup = metas[j], metas[i]

                    # Find the original index of dup in file_list
                    try:
                        dup_idx = file_list.index(dup)
                    except ValueError:
                        continue
                    fuzzy_dups.add(dup_idx)

                    groups.append(
                        DuplicateGroup(
                            kept=kept,
                            duplicates=[dup],
                            reason="fuzzy",
                            similarity=jaccard,
                        )
                    )

    # Build unique list, excluding fuzzy duplicates
    unique_files = [
        meta for idx, meta in enumerate(file_list) if idx not in fuzzy_dups
    ]
    return (unique_files, groups)


# ── Min-hash helpers ───────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, stripping non-alphanumeric edges."""
    tokens: list[str] = []
    for word in text.split():
        cleaned = word.strip(".,;:!?()[]{}'\"«»–—-/\\|@#$%^&*+=<>")
        if cleaned:
            tokens.append(cleaned.lower())
    return tokens


def _make_shingles(tokens: list[str], k: int) -> list[str]:
    """Generate k-word shingles from a token list."""
    if len(tokens) < k:
        return []
    return [" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)]


def _shingle_hash(shingle: str, seed: int) -> int:
    """Deterministic 32-bit hash for a shingle with a given seed.

    Uses MD5 for cross-run stability (Python's built-in hash is randomized).
    Input bytes are identical to ``f"{seed}:{shingle}".encode()``: the
    precomputed seed prefix plus the UTF-8 encoded shingle concatenate to the
    same byte string, so output is bit-identical to the original formulation.
    """
    data = _SEED_PREFIXES[seed] + shingle.encode("utf-8")
    return int.from_bytes(hashlib.md5(data).digest()[:4], "big")


def _minhash_signature(tokens: list[str], num_hashes: int) -> list[int]:
    """Compute a min-hash signature vector for a token list.

    The signature is bit-identical to calling ``_shingle_hash`` per (shingle,
    seed) pair: each MD5 input is ``_SEED_PREFIXES[i] + shingle_bytes``, which
    equals ``f"{i}:{shingle}".encode()``.  Shingles are encoded once instead
    of once-per-seed to avoid ~2.7e8 redundant UTF-8 encodings on large batches.
    """
    shingles = _make_shingles(tokens, _SHINGLE_SIZE)
    if not shingles:
        return [0] * num_hashes

    # Pre-encode each shingle once (avoids re-encoding per seed dimension).
    shingle_bytes = [sh.encode("utf-8") for sh in shingles]
    sig = [_HASH_MOD] * num_hashes
    prefixes = _SEED_PREFIXES
    md5 = hashlib.md5
    for sb in shingle_bytes:
        for i in range(num_hashes):
            h = int.from_bytes(md5(prefixes[i] + sb).digest()[:4], "big")
            if h < sig[i]:
                sig[i] = h
    return sig


def _jaccard_estimate(sig1: list[int], sig2: list[int]) -> float:
    """Estimate Jaccard similarity from two min-hash signatures."""
    if len(sig1) != len(sig2):
        msg = f"Signature lengths differ: {len(sig1)} vs {len(sig2)}"
        raise ValueError(msg)
    if len(sig1) == 0:
        return 0.0
    matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
    return matches / len(sig1)
