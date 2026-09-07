"""Pipeline configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Profile presets ─────────────────────────────────────────────────────────
PROFILE_PRESETS: dict[str, dict] = {
    "quick": dict(
        enable_char_freq_kl=False, enable_html_noisy=False,
        enable_scoring_classifier=False, enable_bilingual_exempt=False,
        enable_line_level_lang=False, enable_trafilatura=False,
        fuzzy_dedup=False, dedup_threshold=0.95,
        ocr_mode="flag-only", table_threshold=0.70,
        contamination_threshold=0.05, suspected_dedup=False,
    ),
    "standard": dict(
        enable_char_freq_kl=True, enable_html_noisy=True,
        enable_scoring_classifier=True, enable_bilingual_exempt=True,
        enable_line_level_lang=False, enable_trafilatura=False,
        fuzzy_dedup=False, dedup_threshold=0.95,
        ocr_mode="flag-only", table_threshold=0.70,
        contamination_threshold=0.05, suspected_dedup=True,
    ),
    "thorough": dict(
        enable_char_freq_kl=True, enable_html_noisy=True,
        enable_scoring_classifier=True, enable_bilingual_exempt=True,
        enable_line_level_lang=True, enable_trafilatura=True,
        fuzzy_dedup=True, dedup_threshold=0.85,
        ocr_mode="clean-light", table_threshold=0.60,
        contamination_threshold=0.03, suspected_dedup=True,
    ),
}
VALID_PROFILES = tuple(PROFILE_PRESETS.keys())


@dataclass
class PipelineConfig:
    """Configuration for the corpus cleaning pipeline.

    Public API: --input, --output, --profile, --dry-run, --lang.
    All internal parameters are set by the profile preset and can be
    overridden individually by advanced users.
    """

    input_path: str
    """Base path containing the corpus folders to clean."""

    output_path: str = "./corpus_cleaned"
    """Directory where cleaned output will be written."""

    profile: str = "standard"
    """Preset profile: quick / standard / thorough."""

    folders: list[str] = field(default_factory=list)
    """Subfolder names to process. Empty means auto-discover folders."""

    table_threshold: float = 0.70
    """Ratio of <table> rows to total rows above which a file is classified as a table file."""

    length_thresholds: tuple[int, int] = (20000, 50000)
    """Net character count boundaries for size buckets: (S/M boundary, M/L boundary)."""

    ocr_mode: str = "flag-only"
    """OCR contamination handling mode: flag-only | clean-mark | clean-light | clean-aggressive."""

    contamination_threshold: float = 0.05
    """Fraction of contaminated characters above which a file is flagged as OCR-contaminated."""

    dry_run: bool = False
    """If True, analyze and report without writing any output files."""

    in_place: bool = False
    """If True, overwrite source files instead of writing to output_path."""

    fuzzy_dedup: bool = False
    """If True, run fuzzy (semantic) deduplication in addition to exact-hash dedup."""

    # ── Profile-controlled switches ────────────────────────────────────────
    enable_ftfy: bool = True
    """Apply ftfy.fix_text() after decoding."""

    enable_fast_langdetect: bool = True
    """Use fast-langdetect instead of langdetect."""

    enable_char_freq_kl: bool = False
    """Detect same-script garbled text via character-frequency KL divergence."""

    enable_html_noisy: bool = False
    """Detect HTML-noisy files (high tag-to-text ratio) beyond table_ratio."""

    enable_scoring_classifier: bool = False
    """Use scoring-based classifier instead of priority-match."""

    enable_bilingual_exempt: bool = False
    """Use extended whitelist (inline code, LaTeX, tech terms)."""

    enable_line_level_lang: bool = False
    """Run per-line language detection for mixed-language files."""

    enable_trafilatura: bool = False
    """Attempt trafilatura extraction for table/HTML-noisy files."""

    enable_ocr: bool = True
    """Enable OCR contamination detection (Stage 3)."""

    suspected_dedup: bool = True
    """Enable suspected (filename-prefix) dedup."""

    # ── Profile-controlled thresholds ──────────────────────────────────────
    dedup_threshold: float = 0.95
    """Jaccard similarity threshold for fuzzy dedup."""

    html_noisy_threshold: float = 0.40
    """HTML tag character ratio above which a file is html_noisy."""

    image_only_min_chars: int = 50
    """Minimum net text chars; below this a file is image_only."""

    char_freq_kl_threshold: float = 2.0
    """KL divergence threshold for same-script garbled text detection."""

    # ── Configurable mappings ──────────────────────────────────────────────
    folder_glob: str = "*"
    """Glob pattern for auto-discovering input subfolders."""

    lang_map: dict[str, str] = field(default_factory=dict)
    """Override folder-name to language-code mapping."""

    lecture_keywords: dict[str, list[str]] = field(default_factory=dict)
    """Override language to lecture keywords mapping."""

    force_lang: str = ""
    """Force a specific language code (e.g. 'AR'), skipping detection."""

    workers: int = 4
    """Number of parallel worker threads for I/O-bound operations."""

    export_cards_path: str = ""
    """If set, export profile cards for passed files to this JSON path after Stage 4 (dedup)
    and stop.  The agent reads this file, generates semantic names, and writes a names JSON.
    Mutually exclusive with import_names_path."""

    import_names_path: str = ""
    """If set, read agent-generated names from this JSON path and use them in Stage 5 (rename)
    instead of the heuristic renamer.  The JSON must contain a 'renamed' list with 'file_id'
    and 'new_name' fields.  Mutually exclusive with export_cards_path."""

    def __post_init__(self) -> None:
        """Apply profile preset, then validate."""
        # Apply profile preset for any field still at its class default.
        if self.profile in PROFILE_PRESETS:
            preset = PROFILE_PRESETS[self.profile]
            for key, value in preset.items():
                if hasattr(self, key):
                    setattr(self, key, value)

        # Validation
        valid_modes = ("flag-only", "clean-mark", "clean-light", "clean-aggressive")
        if self.ocr_mode not in valid_modes:
            msg = f"ocr_mode must be one of {valid_modes!r}, got {self.ocr_mode!r}"
            raise ValueError(msg)
        if self.table_threshold < 0 or self.table_threshold > 1:
            msg = "table_threshold must be between 0 and 1"
            raise ValueError(msg)
        if self.contamination_threshold < 0 or self.contamination_threshold > 1:
            msg = "contamination_threshold must be between 0 and 1"
            raise ValueError(msg)
        if self.length_thresholds[0] >= self.length_thresholds[1]:
            msg = "length_thresholds must be strictly increasing"
            raise ValueError(msg)
        if self.workers < 1:
            msg = "workers must be at least 1"
            raise ValueError(msg)
        if self.profile not in VALID_PROFILES:
            msg = f"profile must be one of {VALID_PROFILES!r}, got {self.profile!r}"
            raise ValueError(msg)
