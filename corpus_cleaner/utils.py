"""Utility functions for corpus cleaning pipeline."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import chardet
import ftfy


# Windows forbidden filename characters: \ / : * ? " < > |
_RE_WINSAFE = re.compile(r'[\\/:*?"<>|]+')
_RE_WHITESPACE = re.compile(r"\s+")
_RE_NON_ASCII = re.compile(r"[^\x00-\x7F]+")


def safe_filename(name: str) -> str:
    """Sanitize a string into a safe Windows-compatible filename.

    Steps:
    1. Replace Windows forbidden characters (\\ / : * ? " < > |) with underscore.
    2. Replace non-ASCII sequences (Arabic, Cyrillic, CJK, etc.) with underscore.
    3. Collapse consecutive whitespace to a single underscore.
    4. Strip leading/trailing underscores and dots.
    5. Lowercase.
    6. Truncate to 200 characters.

    Args:
        name: Raw filename or title string.

    Returns:
        A safe, ASCII-only, Windows-compatible filename candidate.
    """
    # Replace forbidden chars
    result = _RE_WINSAFE.sub("_", name)
    # Replace non-ASCII (Arabic/Cyrillic/CJK) with underscore
    result = _RE_NON_ASCII.sub("_", result)
    # Collapse whitespace (including underscores from replacements)
    result = _RE_WHITESPACE.sub("_", result)
    # Strip leading/trailing underscores and dots
    result = result.strip("_.")
    # Lowercase
    result = result.lower()
    # Truncate
    if len(result) > 200:
        result = result[:200]
    # Fallback if everything was stripped
    if not result:
        result = "untitled"
    return result


def md5_file(path: Path) -> str:
    """Compute the MD5 hex digest of a file's content.

    Args:
        path: Path to the file.

    Returns:
        32-character lowercase hexadecimal MD5 digest.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If the file cannot be read.
    """
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def read_file_auto(path: Path) -> tuple[str, str]:
    """Read a text file with automatic encoding detection.

    Uses chardet to detect encoding, falling back to UTF-8 then latin-1.

    Args:
        path: Path to the text file.

    Returns:
        A tuple of (decoded_text, detected_encoding_name).

    Raises:
        FileNotFoundError: If the file does not exist.
        UnicodeDecodeError: If the file cannot be decoded by any supported encoding.
    """
    raw = path.read_bytes()

    if len(raw) == 0:
        return ("", "utf-8")

    detected = chardet.detect(raw)
    encoding = detected.get("encoding") or "utf-8"
    confidence = detected.get("confidence", 0.0)

    # Try detected encoding first, then UTF-8, then latin-1 as last resort
    for enc in (encoding, "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            text = ftfy.fix_text(text)
            return (text, enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # latin-1 never raises UnicodeDecodeError, so we should never reach here
    msg = f"Unable to decode {path}"
    raise UnicodeDecodeError("unknown", b"", 0, 1, msg)
