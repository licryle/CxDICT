"""Cleanup CLI: maintain human and LLM datasets as deltas over the base dictionary.

Usage:
    python scripts/cleanup.py --language CODE [--dry-run] [--base PATH]
                                [--human PATH] [--llm-generated PATH]

Applies spec §9 precedence (base > human.u8 > llm_generated.json),
rewriting the datasets atomically unless --dry-run is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..cleanup import cleanup_files
from ..languages import LANGUAGES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=sorted(LANGUAGES),
                        help="target dictionary language")
    parser.add_argument("--base", default="data/cfdict.u8")
    parser.add_argument("--human", default="data/human.u8")
    parser.add_argument("--llm-generated", default="data/llm_generated.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = cleanup_files(
            args.base, args.human, args.llm_generated, args.dry_run
        )
    except (ValueError, OSError) as exc:
        print(f"cleanup failed: {exc}", file=sys.stderr)
        return 1
    mode = "dry run — no files written" if args.dry_run else "datasets rewritten"
    print(f"cleanup done ({mode}):")
    print(
        f"  human: {report.human_before} -> {report.human_after} "
        f"(removed {report.human_removed_base} now in base)"
    )
    print(
        f"  llm_generated: {report.llm_before} -> {report.llm_after} "
        f"(removed {report.llm_removed_base} now in base, "
        f"{report.llm_removed_human} now human)"
    )
    return 0


