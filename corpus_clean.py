"""CLI entry point for corpus-clean tool.

Usage:
    python corpus_clean.py --input <folder> --output corpus_cleaned/ \
        --profile standard [--dry-run] [--lang AR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corpus_cleaner.config import PipelineConfig, VALID_PROFILES
from corpus_cleaner.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with profile-based public API."""
    parser = argparse.ArgumentParser(
        prog="corpus-clean",
        description="Clean and organize multilingual corpus files.",
    )
    # ── Public API (5 params) ──────────────────────────────────────────────
    parser.add_argument(
        "--input", "-i",
        required=True,
        type=str,
        help="Base path containing corpus folders to@ clean.",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="./corpus_cleaned",
        help="Output directory for cleaned files (default: ./corpus_cleaned).",
    )
    parser.add_argument(
        "--profile", "-p",
        type=str,
        default="standard",
        choices=list(VALID_PROFILES),
        help="Preset profile: quick / standard / thorough (default: standard).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Analyze without writing output files.",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="",
        help="Force language code (e.g. AR, FR, RU, EN) — skip detection.",
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm execution after dry-run review (required without --dry-run).",
    )
    # ── Hidden/advanced overrides ──────────────────────────────────────────
    adv = parser.add_argument_group("advanced", "Override profile defaults (rarely needed)")
    adv.add_argument("--folders", "-f", type=str, nargs="*", default=[], help=argparse.SUPPRESS)
    adv.add_argument("--table-threshold", type=float, default=None, help=argparse.SUPPRESS)
    adv.add_argument("--ocr-mode", type=str, default=None,
                     choices=["flag-only", "clean-mark", "clean-light", "clean-aggressive"],
                     help=argparse.SUPPRESS)
    adv.add_argument("--contamination-threshold", type=float, default=None, help=argparse.SUPPRESS)
    adv.add_argument("--length-thresholds", type=str, default=None, help=argparse.SUPPRESS)
    adv.add_argument("--fuzzy-dedup", action="store_true", default=False, help=argparse.SUPPRESS)
    adv.add_argument("--in-place", action="store_true", default=False, help=argparse.SUPPRESS)
    adv.add_argument("--workers", "-j", type=int, default=None, help=argparse.SUPPRESS)
    adv.add_argument("--export-cards", type=str, default="", metavar="PATH.json", help=argparse.SUPPRESS)
    adv.add_argument("--import-names", type=str, default="", metavar="PATH.json", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    """Main entry point for the corpus-clean CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Safety guard: require --confirm for non-dry-run execution.
    if not args.dry_run and not args.confirm:
        print(
            "Error: non-dry-run execution requires --confirm.\n"
            "Run with --dry-run first to preview, then re-run with --confirm.",
            file=sys.stderr,
        )
        return 2

    # Validate input path exists.
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input path does not exist: {args.input}", file=sys.stderr)
        return 1
    if not input_path.is_dir():
        print(f"Error: input path is not a directory: {args.input}", file=sys.stderr)
        return 1

    # Parse length thresholds if provided.
    length_thresholds: tuple[int, int] = (20000, 50000)
    if args.length_thresholds:
        parts = args.length_thresholds.split(",")
        if len(parts) != 2:
            parser.error("--length-thresholds must be two comma-separated integers")
        try:
            length_thresholds = (int(parts[0]), int(parts[1]))
        except ValueError:
            parser.error(f"--length-thresholds values must be integers, got {args.length_thresholds!r}")

    # Build config — profile preset fills defaults, then overrides apply.
    config = PipelineConfig(
        input_path=str(input_path),
        output_path=args.output,
        profile=args.profile,
        folders=list(args.folders) if args.folders else [],
        length_thresholds=length_thresholds,
        dry_run=args.dry_run,
        force_lang=args.lang,
    )

    # Apply advanced overrides on top of profile preset.
    if args.table_threshold is not None:
        config.table_threshold = args.table_threshold
    if args.ocr_mode is not None:
        config.ocr_mode = args.ocr_mode
    if args.contamination_threshold is not None:
        config.contamination_threshold = args.contamination_threshold
    if args.fuzzy_dedup:
        config.fuzzy_dedup = True
    if args.in_place:
        config.in_place = True
    if args.workers is not None:
        config.workers = args.workers
    if args.export_cards:
        config.export_cards_path = args.export_cards
    if args.import_names:
        config.import_names_path = args.import_names

    try:
        results = run_pipeline(config)
    except Exception as exc:
        print(f"Error: pipeline failed: {exc}", file=sys.stderr)
        return 1

    stats = results.get("stats", {})

    if config.export_cards_path:
        print(f"\nProfile cards exported: {stats.get('exported_cards', 0)} files")
        print(f"Cards written to: {config.export_cards_path}")
        print(f"\nNext: agent reads cards and generates names, then:")
        print(f"  corpus-clean --input {config.input_path} --import-names names.json")
        return 0

    if config.import_names_path:
        print(f"\nAgent names loaded from: {config.import_names_path}")

    # Print summary.
    print(f"\nCorpus Cleaning Complete")
    print(f"{'=' * 40}")
    print(f"  Total scanned:     {stats.get('total_scanned', 0):>5}")
    print(f"  Passed (clean):    {stats.get('passed', 0):>5}")
    print(f"  Bad files:         {stats.get('bad', 0):>5}")
    print(f"  Empty files:       {stats.get('empty', 0):>5}")
    print(f"  Table files:       {stats.get('table', 0):>5}")
    print(f"  Contaminated:      {stats.get('contaminated', 0):>5}")
    print(f"  Duplicates total:  {stats.get('duplicates_total', 0):>5}")
    print(f"    - Exact:         {stats.get('duplicates_exact', 0):>5}")
    print(f"    - Suspected:     {stats.get('duplicates_suspected', 0):>5}")
    print(f"    - Fuzzy:         {stats.get('duplicates_fuzzy', 0):>5}")
    print(f"{'=' * 40}")
    print(f"  Profile: {config.profile}")
    print(f"Report written to: {Path(args.output) / '_report.xlsx'}")
    print(f"Summary written to: {Path(args.output) / '_summary.txt'}")

    if args.dry_run:
        print("\n[Dry run — no files were written]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
