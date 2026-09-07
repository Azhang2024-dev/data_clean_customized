"""Internationalization token whitelist regex patterns.

These patterns define content that is considered "legally bilingual" —
i.e., non-target-language text that should NOT be flagged as OCR contamination.

Defined in plan Section 3, Stage 3.
"""

from __future__ import annotations

import re

# 1. URLs — https://... or http://...
RE_URL: re.Pattern[str] = re.compile(r"https?://\S+")

# 2. Email addresses
RE_EMAIL: re.Pattern[str] = re.compile(r"\S+@[a-zA-Z0-9._-]+\.[a-zA-Z]+")

# 3. All-uppercase English acronyms (3+ characters after the first)
#    e.g., PDF, HTTP, API, UUID, JSON
RE_ABBREV: re.Pattern[str] = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")

# 4. Numbers with units — e.g., 42%, 3.14 kg, 100px
RE_NUM_UNIT: re.Pattern[str] = re.compile(r"\d+(\.\d+)?\s*(%|[a-zA-Z]+)")

# 5. HTML <img> tags
RE_IMG_TAG: re.Pattern[str] = re.compile(r"<img\s[^>]*>")

# 6. Markdown image syntax — ![alt](url)
RE_MD_IMG: re.Pattern[str] = re.compile(r"!\[[^\]]*\]\([^)]+\)")

# 7. Generic HTML tags/attributes (whitelist for HTML noise)
RE_HTML_ATTR: re.Pattern[str] = re.compile(r"<[^>]+>")

# Combined whitelist pattern — all legally bilingual tokens
RE_WHITELIST: re.Pattern[str] = re.compile(
    "|".join(
        p.pattern
        for p in (RE_URL, RE_EMAIL, RE_ABBREV, RE_NUM_UNIT, RE_IMG_TAG, RE_MD_IMG, RE_HTML_ATTR)
    )
)


# ══════════════════════════════════════════════════════════════════════════════
# Extended whitelist (standard/thorough profiles)
# ══════════════════════════════════════════════════════════════════════════════

# 8. Inline code — code or `code`
RE_INLINE_CODE: re.Pattern[str] = re.compile(r"`[^`]+`")

# 9. LaTeX math — $...$ or ...
RE_LATEX: re.Pattern[str] = re.compile(r"\$+[^$]+\$+")

# 10. Technical terms with mixed script — e.g., "3G", "WiFi", "COVID-19"
RE_TECH_TERM: re.Pattern[str] = re.compile(r"\b[A-Z][a-zA-Z0-9]*-[A-Za-z0-9]+\b|\b[A-Z]{2,}[a-z]+\b")

# Combined extended whitelist pattern
RE_WHITELIST_EXTENDED: re.Pattern[str] = re.compile(
    "|".join(
        p.pattern
        for p in (RE_URL, RE_EMAIL, RE_ABBREV, RE_NUM_UNIT, RE_IMG_TAG, RE_MD_IMG,
                  RE_HTML_ATTR, RE_INLINE_CODE, RE_LATEX, RE_TECH_TERM)
    )
)
