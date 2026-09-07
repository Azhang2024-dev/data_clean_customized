#!/usr/bin/env python3
"""Install corpus-cleaner skill to ~/.agents/skills/.

Usage:
    python install_skill.py                  # Copy SKILL.md only
    python install_skill.py --install-deps   # Copy SKILL.md + pip install -e .
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_SRC = Path(__file__).resolve().parent / "skills" / "corpus-cleaner" / "SKILL.md"
SKILL_DST = Path.home() / ".agents" / "skills" / "corpus-cleaner" / "SKILL.md"


def install_skill() -> bool:
    """Copy SKILL.md to ~/.agents/skills/corpus-cleaner/.

    Returns True on success, False on failure.
    """
    if not SKILL_SRC.exists():
        print(f"Error: SKILL.md not found at {SKILL_SRC}")
        return False

    try:
        SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL_SRC, SKILL_DST)
        print(f"SKILL.md installed to {SKILL_DST}")
        return True
    except (OSError, shutil.Error) as exc:
        print(f"Error: failed to install SKILL.md: {exc}")
        return False


def install_deps() -> bool:
    """Run pip install -e . in the project root.

    Returns True on success, False on failure.
    """
    project_root = Path(__file__).resolve().parent
    print(f"Installing dependencies from {project_root} ...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(project_root)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"Error: pip install failed:\n{result.stderr}")
            return False
        print("Dependencies installed successfully.")
        return True
    except subprocess.TimeoutExpired:
        print("Error: pip install timed out (120s).")
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="install_skill",
        description="Install corpus-cleaner skill to ~/.agents/skills/.",
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        default=False,
        help="Also run pip install -e . to register the corpus-clean CLI.",
    )
    args = parser.parse_args()

    ok = install_skill()

    if args.install_deps:
        ok = ok and install_deps()

    if ok:
        print("\nInstallation complete.")
        if args.install_deps:
            print("Use 'corpus-clean --help' to verify the CLI is available.")
        return 0

    print("\nInstallation failed. See errors above.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
