"""Generation orchestrator CLI: fill the LLM dataset from the missing scope.

Usage:
    python scripts/generate.py [--env PATH] [--cfdict PATH] [--cc-cedict PATH]
                                [--human PATH] [--llm-generated PATH]
                                [--cc-version LABEL] [--batch-size N]
                                [--limit N] [--dry-run]

Computes CC-CEDICT − base − human.u8 − llm_generated.json (spec §3, §5),
generates French definitions in batches through the configured
OpenAI-compatible endpoint, and merges the records into llm_generated.json.

Safety: --limit caps entries per run (default 20); pass --limit 0 for a
full-scope run. --dry-run plans without calling the endpoint or writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..generation.config import load_config
from ..generation.llm import GenerationError
from ..generation.orchestrator import generate_files
from ..scope_info import sha256_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--cfdict", default="data/cfdict.u8")
    parser.add_argument(
        "--cc-cedict", default="data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
    )
    parser.add_argument("--human", default="data/human.u8")
    parser.add_argument("--llm-generated", default="data/llm_generated.json")
    parser.add_argument("--cc-version", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    if args.limit < 0:
        print("generate failed: --limit must be >= 0 (0 = unlimited)", file=sys.stderr)
        return 1
    try:
        config = load_config(args.env)
    except (ValueError, OSError) as exc:
        print(f"generate failed: {exc}", file=sys.stderr)
        return 1
    if args.batch_size is not None:
        if args.batch_size <= 0:
            print("generate failed: --batch-size must be positive", file=sys.stderr)
            return 1
        import dataclasses

        config = dataclasses.replace(config, batch_size=args.batch_size)
    try:
        cc_version = args.cc_version or sha256_file(args.cc_cedict)
        report = generate_files(
            args.cfdict,
            args.cc_cedict,
            args.human,
            args.llm_generated,
            config,
            cc_version,
            limit=args.limit,
            dry_run=args.dry_run,
            progress=not args.no_progress,
        )
    except (ValueError, OSError, GenerationError) as exc:
        print(f"generate failed: {exc}", file=sys.stderr)
        return 1
    plan = report.plan
    if args.dry_run:
        print(
            f"dry run — no endpoint calls, no files written: "
            f"{plan.scoped} entries in missing scope, "
            f"{plan.limited_to} planned in {plan.batches} batch(es)"
        )
    else:
        print(
            f"generate done: {plan.limited_to}/{plan.scoped} entries in "
            f"{plan.batches} batch(es) -> {report.llm_new} generated"
        )
        if plan.limited_to < plan.scoped:
            print(
                f"scope truncated by --limit {args.limit}; re-run for the rest "
                f"(already-written entries are skipped next time)"
            )
    return 0


