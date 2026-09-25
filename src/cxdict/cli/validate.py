"""Validation CLI: gate releases on data relationships (spec §14).

Usage:
    python scripts/validate.py --language CODE [--base PATH] [--cc-cedict PATH]
                                [--human PATH] [--llm-generated PATH]
                                [--out-human PATH] [--out-full PATH]

Validates inputs always; validates assembled outputs when both --out-*
paths are given. Exits 1 with named reasons on any violation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..languages import resolve_paths
from ..validation import check_outputs, validate_inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True,
                        help="target dictionary language code (see dictionaries/)")
    parser.add_argument("--base", default=None,
                        help="base dictionary file (default: dictionaries/<language>/data/…)")
    parser.add_argument("--cc-cedict", default=None,
                        help="CC-CEDICT file (default: dictionaries/cc-cedict/…)")
    parser.add_argument("--human", default=None,
                        help="human curation file (default: dictionaries/<language>/data/human.u8)")
    parser.add_argument("--llm-generated", default=None,
                        help="LLM dataset file (default: dictionaries/<language>/data/llm_generated.json)")
    parser.add_argument("--out-human", default=None)
    parser.add_argument("--out-full", default=None)
    args = parser.parse_args(argv)
    try:
        paths = resolve_paths(
            args.language, base=args.base, cc_cedict=args.cc_cedict,
            human=args.human, llm_generated=args.llm_generated,
        )
    except (ValueError, OSError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    report, data = validate_inputs(
        paths.base, paths.cc_cedict, paths.human, paths.llm_generated
    )
    out_human = args.out_human
    if data is not None and out_human and args.out_full:
        check_outputs(
            out_human,
            args.out_full,
            data["base_ids"],
            data["human_ids"],
            set(data["llm_generated"]),
            report,
        )
    for check in report.checks:
        status = "ok  " if check.passed else "FAIL"
        detail = f" — {check.detail}" if check.detail else ""
        print(f"{status} {check.name}{detail}")
    if not report.passed:
        print(f"validation failed: {len(report.failures())} check(s)", file=sys.stderr)
        return 1
    print("validation passed")
    return 0


