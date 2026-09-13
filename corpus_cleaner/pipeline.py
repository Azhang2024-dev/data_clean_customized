"""Pipeline orchestrator — runs all 7 cleaning stages in sequence.

Stages:
    1. Scan — discover and parse corpus files
    2. Table filter — route table/empty/bad/html_noisy/image_only files to isolation buckets
    3. OCR contamination — detect and optionally clean OCR noise (+ KL divergence)
    4. Deduplicate — exact + suspected + optional fuzzy dedup
    5. Classify + Rename — categorize and generate semantic filenames
    6. Output — write files to output directory structure
    7. Report — generate Excel, text summary, and JSON manifest
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from corpus_cleaner import classifier
from corpus_cleaner import deduplicator
from corpus_cleaner import ocr_handler
from corpus_cleaner import renamer
from corpus_cleaner import reporter
from corpus_cleaner import scanner
from corpus_cleaner import table_filter
from corpus_cleaner.config import PipelineConfig
from corpus_cleaner.i18n_tokens import RE_WHITELIST, RE_WHITELIST_EXTENDED
from corpus_cleaner.profile_card import extract_profile_card, ProfileCard
from corpus_cleaner.utils import md5_file


def run_pipeline(config: PipelineConfig) -> dict[str, Any]:
    """Execute the full corpus cleaning pipeline.

    Args:
        config: Pipeline configuration from CLI or programmatic setup.

    Returns:
        Summary dict with keys:
            files: list[dict] — all file records for reporter
            contaminated: list[dict] — OCR-contaminated file details
            duplicates: list[dict] — duplicate group records
            bad_files: list[dict] — unreadable file records
            stats: dict — per-stage counts
    """
    # ── Stage 1: Scan ──────────────────────────────────────────────────────
    all_files: list[scanner.FileMeta] = scanner.scan_files(config)

    # ── Stage 2: Table filter ──────────────────────────────────────────────
    ok_files: list[scanner.FileMeta] = []
    bad_metas: list[scanner.FileMeta] = []
    empty_metas: list[scanner.FileMeta] = []
    table_metas: list[scanner.FileMeta] = []
    html_noisy_metas: list[scanner.FileMeta] = []
    image_only_metas: list[scanner.FileMeta] = []

    for meta in all_files:
        meta_dict = _meta_to_dict(meta)
        if meta.detected_lang == "error" and meta.line_count == -1:
            bad_metas.append(meta)
            continue

        status = table_filter.classify_file_status(
            meta_dict, meta.content or "", config.table_threshold
        )
        if status == "bad":
            bad_metas.append(meta)
        elif status == "empty":
            empty_metas.append(meta)
        elif status == "table":
            table_metas.append(meta)
        elif status == "html_noisy":
            html_noisy_metas.append(meta)
        elif status == "image_only":
            image_only_metas.append(meta)
        else:
            ok_files.append(meta)

    # ── trafilatura rescue (thorough only) ──────────────────────────────────
    # Attempt to extract clean text from html_noisy files via trafilatura.
    # If extraction succeeds, promote them to ok_files.
    if config.enable_trafilatura and html_noisy_metas:
        rescued: list[scanner.FileMeta] = []
        still_noisy: list[scanner.FileMeta] = []
        for meta in html_noisy_metas:
            extracted = table_filter.extract_html_content(meta.content or "")
            if extracted is not None:
                meta.content = extracted
                # Recompute basic metrics on extracted text.
                meta.line_count = len(extracted.splitlines())
                meta.raw_char_count = len(extracted)
                rescued.append(meta)
            else:
                still_noisy.append(meta)
        ok_files.extend(rescued)
        html_noisy_metas = still_noisy

    # ── Stage 3: OCR contamination ─────────────────────────────────────────
    contaminated_metas: list[scanner.FileMeta] = []
    clean_ok_files: list[scanner.FileMeta] = []

    for meta in ok_files:
        content = meta.content or ""
        _wl = RE_WHITELIST_EXTENDED if config.enable_bilingual_exempt else RE_WHITELIST
        score, _details = ocr_handler.compute_contamination(
            content, meta.primary_lang, config.contamination_threshold,
            whitelist=_wl
        )
        meta.contamination_score = score

        # KL divergence check for same-script garbled text (standard/thorough).
        if config.enable_char_freq_kl:
            kl_score = ocr_handler.compute_char_freq_kl(
                content, meta.primary_lang, config.char_freq_kl_threshold
            )
            if kl_score > config.char_freq_kl_threshold and score <= config.contamination_threshold:
                meta.contamination_score = max(score, config.contamination_threshold + 0.001)
                score = meta.contamination_score

        if score > config.contamination_threshold:
            if config.ocr_mode != "flag-only":
                cleaned, _changes = ocr_handler.clean_content(
                    content, meta.primary_lang, config.ocr_mode,
                    whitelist=_wl
                )
                meta.content = cleaned
            contaminated_metas.append(meta)
        else:
            clean_ok_files.append(meta)

    # ── Stage 4: Deduplicate ───────────────────────────────────────────────
    dedup_input: list[deduplicator.FileMeta] = [
        _to_dedup_meta(m) for m in clean_ok_files
    ]
    dedup_unique, dup_groups = deduplicator.find_duplicates(
        dedup_input, fuzzy=config.fuzzy_dedup, fuzzy_threshold=config.dedup_threshold
    )

    # Map dedup results back to scanner.FileMeta.
    dedup_kept: set[Path] = {d.path for d in dedup_unique}
    duplicate_metas: list[scanner.FileMeta] = []
    passed_files: list[scanner.FileMeta] = []

    for meta in clean_ok_files:
        if meta.path in dedup_kept:
            passed_files.append(meta)
        else:
            duplicate_metas.append(meta)

    if config.export_cards_path:
        return _export_cards(passed_files, config)

    # ── Stage 5: Classify + Rename ─────────────────────────────────────────
    seq_counter: dict[tuple[str, str], int] = defaultdict(int)
    file_records: list[dict[str, Any]] = []

    agent_names: dict[str, str] = {}
    if config.import_names_path:
        agent_names = _load_agent_names(config.import_names_path)

    for meta in passed_files:
        content = meta.content or ""
        meta_dict = _meta_to_dict(meta)
        if config.enable_scoring_classifier:
            category = classifier.classify_file_scoring(meta_dict, content, meta.primary_lang)
        else:
            category = classifier.classify_file(meta_dict, content)
        key = (meta.primary_lang, category)
        seq_counter[key] += 1

        file_id = meta.path.stem
        if file_id in agent_names:
            new_name = agent_names[file_id]
        else:
            new_name = renamer.generate_new_name(
                meta_dict, content, category, seq_counter[key],
                config.length_thresholds,
            )
        file_records.append({
            "source_folder": meta.source_folder,
            "original_name": meta.path.name,
            "new_name": new_name,
            "category": category,
            "primary_lang": meta.primary_lang,
            "detected_lang": meta.detected_lang,
            "line_count": meta.line_count,
            "raw_char_count": meta.raw_char_count,
            "net_char_count": meta.net_char_count,
            "length_bracket": meta.length_bracket,
            "table_ratio": meta.table_ratio,
            "contamination_score": meta.contamination_score,
            "status": "ok",
            "reason": "",
        })

    # ── Build records for isolated files ────────────────────────────────────
    _append_isolated_records(file_records, table_metas, "table")
    _append_isolated_records(file_records, contaminated_metas, "contaminated")
    _append_isolated_records(file_records, empty_metas, "empty")
    _append_isolated_records(file_records, bad_metas, "bad")
    _append_isolated_records(file_records, html_noisy_metas, "html_noisy")
    _append_isolated_records(file_records, image_only_metas, "image_only")

    # Duplicate records: one per duplicate (not the kept copy).
    for meta in duplicate_metas:
        file_records.append({
            "source_folder": meta.source_folder,
            "original_name": meta.path.name,
            "new_name": "",
            "category": "",
            "primary_lang": meta.primary_lang,
            "detected_lang": meta.detected_lang,
            "line_count": meta.line_count,
            "raw_char_count": meta.raw_char_count,
            "net_char_count": meta.net_char_count,
            "length_bracket": meta.length_bracket,
            "table_ratio": meta.table_ratio,
            "contamination_score": meta.contamination_score,
            "status": "duplicate",
            "reason": "",
        })

    # ── Contaminated record details for reporter ───────────────────────────
    contaminated_records: list[dict[str, Any]] = []
    for meta in contaminated_metas:
        lines = (meta.content or "").splitlines()
        sample = "\n".join(lines[:3])
        contaminated_records.append({
            "filename": meta.path.name,
            "score": meta.contamination_score,
            "sample_lines": sample,
        })

    # ── Duplicate group records for reporter ───────────────────────────────
    duplicate_records: list[dict[str, Any]] = []
    for group in dup_groups:
        duplicate_records.append({
            "kept_name": group.kept.path.name,
            "duplicate_names": [d.path.name for d in group.duplicates],
            "similarity": group.similarity,
        })

    # ── Bad file records for reporter ──────────────────────────────────────
    bad_file_records: list[dict[str, Any]] = []
    for meta in bad_metas:
        bad_file_records.append({
            "filename": meta.path.name,
            "error": "Unreadable or binary file",
        })

    # ── Stage 6: Output ────────────────────────────────────────────────────
    if not config.dry_run:
        out = Path(config.output_path)
        if config.in_place:
            _write_files_in_place(passed_files, contaminated_metas)
        else:
            _write_files_to_output(
                out, passed_files, table_metas, contaminated_metas,
                duplicate_metas, dup_groups, empty_metas, bad_metas,
                html_noisy_metas, image_only_metas,
                file_records,
            )

    # ── Stage 7: Report ────────────────────────────────────────────────────
    results: dict[str, Any] = {
        "files": file_records,
        "contaminated": contaminated_records,
        "duplicates": duplicate_records,
        "bad_files": bad_file_records,
    }
    reporter.generate_report(results, config.output_path)

    # ── Stats ──────────────────────────────────────────────────────────────
    exact_dup_count = sum(
        1 for g in dup_groups if g.reason == "exact"
    )
    suspected_dup_count = sum(
        1 for g in dup_groups if g.reason == "suspected"
    )
    fuzzy_dup_count = sum(
        1 for g in dup_groups if g.reason == "fuzzy"
    )

    results["stats"] = {
        "total_scanned": len(all_files),
        "bad": len(bad_metas),
        "empty": len(empty_metas),
        "table": len(table_metas),
        "html_noisy": len(html_noisy_metas),
        "image_only": len(image_only_metas),
        "contaminated": len(contaminated_metas),
        "duplicates_exact": exact_dup_count,
        "duplicates_suspected": suspected_dup_count,
        "duplicates_fuzzy": fuzzy_dup_count,
        "duplicates_total": len(duplicate_metas),
        "passed": len(passed_files),
    }

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════


def _meta_to_dict(meta: scanner.FileMeta) -> dict[str, Any]:
    """Convert a scanner FileMeta to a dict for classifier/table_filter/renamer."""
    return {
        "line_count": meta.line_count,
        "table_ratio": meta.table_ratio,
        "net_char_count": meta.net_char_count,
        "length_bracket": meta.length_bracket,
        "status": (
            "bad" if meta.detected_lang == "error" and meta.line_count == -1
            else "ok"
        ),
    }


def _to_dedup_meta(meta: scanner.FileMeta) -> deduplicator.FileMeta:
    """Convert a scanner FileMeta to a deduplicator FileMeta."""
    try:
        mtime = meta.path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return deduplicator.FileMeta(
        path=meta.path,
        file_id=meta.file_id,
        hash_from_name=meta.hash,
        content_md5="",
        timestamp=mtime,
        primary_lang=meta.primary_lang,
    )


def _append_isolated_records(
    records: list[dict[str, Any]],
    metas: list[scanner.FileMeta],
    status: str,
) -> None:
    """Append file records for isolated (non-passed) files."""
    for meta in metas:
        records.append({
            "source_folder": meta.source_folder,
            "original_name": meta.path.name,
            "new_name": "",
            "category": "",
            "primary_lang": meta.primary_lang,
            "detected_lang": meta.detected_lang,
            "line_count": meta.line_count,
            "raw_char_count": meta.raw_char_count,
            "net_char_count": meta.net_char_count,
            "length_bracket": meta.length_bracket,
            "table_ratio": meta.table_ratio,
            "contamination_score": meta.contamination_score,
            "status": status,
            "reason": "",
        })


# ══════════════════════════════════════════════════════════════════════════════
# Stage 6 — File writing
# ══════════════════════════════════════════════════════════════════════════════


def _write_files_to_output(
    out: Path,
    passed_files: list[scanner.FileMeta],
    table_metas: list[scanner.FileMeta],
    contaminated_metas: list[scanner.FileMeta],
    duplicate_metas: list[scanner.FileMeta],
    dup_groups: list[deduplicator.DuplicateGroup],
    empty_metas: list[scanner.FileMeta],
    bad_metas: list[scanner.FileMeta],
    html_noisy_metas: list[scanner.FileMeta],
    image_only_metas: list[scanner.FileMeta],
    file_records: list[dict[str, Any]],
) -> None:
    """Write cleaned and isolated files to the output directory structure.

    Directory layout:
        {lang}/                  — passed files, renamed
        _tables/{lang}/          — table-dominant files
        _contaminated/{lang}/    — OCR-contaminated files
        _html_noisy/{lang}/      — HTML-noisy files
        _image_only/{lang}/      — image-only files
        _duplicates/exact/       — exact duplicates
        _duplicates/suspected/   — suspected duplicates
        _empty/                  — empty files
        _bad_files/              — unreadable files
    """
    # Build lookup: original_name → new_name for passed files.
    name_map: dict[str, str] = {}
    for rec in file_records:
        if rec.get("status") == "ok" and rec.get("new_name"):
            name_map[rec["original_name"]] = rec["new_name"]

    # Passed files → {lang}/{new_name}
    for meta in passed_files:
        new_name = name_map.get(meta.path.name, meta.path.name)
        lang_dir = out / meta.primary_lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        _copy_file(meta, lang_dir / new_name)

    # Table files → _tables/{lang}/{original_name}
    for meta in table_metas:
        lang_dir = out / "_tables" / meta.primary_lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        _copy_file(meta, lang_dir / meta.path.name)

    # Contaminated files → _contaminated/{lang}/{original_name}
    for meta in contaminated_metas:
        lang_dir = out / "_contaminated" / meta.primary_lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        _copy_file(meta, lang_dir / meta.path.name)

    # Duplicates → _duplicates/exact/ or _duplicates/suspected/
    for group in dup_groups:
        subdir = out / "_duplicates" / group.reason
        subdir.mkdir(parents=True, exist_ok=True)
        for dup_meta in group.duplicates:
            src_path = dup_meta.path
            if src_path.exists():
                shutil.copy2(str(src_path), str(subdir / src_path.name))

    # Empty files → _empty/
    if empty_metas:
        empty_dir = out / "_empty"
        empty_dir.mkdir(parents=True, exist_ok=True)
        for meta in empty_metas:
            _copy_file(meta, empty_dir / meta.path.name)

    # Bad files → _bad_files/
    if bad_metas:
        bad_dir = out / "_bad_files"
        bad_dir.mkdir(parents=True, exist_ok=True)
        for meta in bad_metas:
            _copy_file(meta, bad_dir / meta.path.name)

    # HTML-noisy files → _html_noisy/{lang}/
    for meta in html_noisy_metas:
        lang_dir = out / "_html_noisy" / meta.primary_lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        _copy_file(meta, lang_dir / meta.path.name)

    # Image-only files → _image_only/{lang}/
    for meta in image_only_metas:
        lang_dir = out / "_image_only" / meta.primary_lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        _copy_file(meta, lang_dir / meta.path.name)


def _write_files_in_place(
    passed_files: list[scanner.FileMeta],
    contaminated_metas: list[scanner.FileMeta],
) -> None:
    """Overwrite cleaned content back to source files for passed/contaminated files only."""
    for meta in passed_files:
        if meta.content is not None:
            meta.path.write_text(meta.content, encoding="utf-8")

    for meta in contaminated_metas:
        if meta.content is not None:
            meta.path.write_text(meta.content, encoding="utf-8")


def _copy_file(meta: scanner.FileMeta, dest: Path) -> None:
    """Copy a file, using in-memory content if available, otherwise disk copy."""
    if meta.content is not None:
        dest.write_text(meta.content, encoding="utf-8")
    elif meta.path.exists():
        shutil.copy2(str(meta.path), str(dest))


def _export_cards(
    passed_files: list[scanner.FileMeta], config: PipelineConfig
) -> dict[str, Any]:
    """Export profile cards for agent-based semantic renaming.

    Extracts a ProfileCard for each passed file and writes them to
    ``config.export_cards_path`` as JSON.  Returns a summary dict so
    the CLI can display stats.
    """
    cards_data: list[dict[str, Any]] = []
    seq_counter: dict[str, int] = defaultdict(int)

    for meta in passed_files:
        content = meta.content or ""
        meta_dict = _meta_to_dict(meta)
        if config.enable_scoring_classifier:
            category = classifier.classify_file_scoring(meta_dict, content, meta.primary_lang)
        else:
            category = classifier.classify_file(meta_dict, content)
        seq_counter[category] += 1

        card = extract_profile_card(
            content=content,
            file_id=meta.path.stem,
            original_name=meta.path.name,
            category=category,
            primary_lang=meta.primary_lang,
            net_char_count=meta.net_char_count,
            size_bracket=meta.length_bracket,
        )
        card_dict = {
            "file_id": card.file_id,
            "original_name": card.original_name,
            "category": card.category,
            "headings": card.headings,
            "first_text": card.first_text,
            "keywords": card.keywords,
            "size_bracket": card.size_bracket,
            "net_char_count": card.net_char_count,
            "ocr_contamination": card.ocr_contamination,
            "table_ratio": card.table_ratio,
            "primary_lang": card.primary_lang,
            "seq": seq_counter[category],
        }
        cards_data.append(card_dict)

    export = {
        "source_folder": str(config.input_path),
        "total_files": len(cards_data),
        "cards": cards_data,
    }

    out_path = Path(config.export_cards_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "files": [],
        "contaminated": [],
        "duplicates": [],
        "bad_files": [],
        "stats": {
            "exported_cards": len(cards_data),
            "cards_path": str(out_path),
        },
    }


def _load_agent_names(import_path: str) -> dict[str, str]:
    """Load agent-generated names from a JSON file.

    Expected format: {"renamed": [{"file_id": "...", "new_name": "..."}, ...]}
    Returns a dict mapping file_id → new_name.
    """
    data = json.loads(Path(import_path).read_text(encoding="utf-8"))
    name_map: dict[str, str] = {}
    for entry in data.get("renamed", []):
        name_map[entry["file_id"]] = entry["new_name"]
    return name_map
