"""Validation CLI: gate releases on data relationships (spec §14).

Usage:
    python scripts/validate.py --language CODE [--base PATH] [--cc-cedict PATH]
                                [--cc-cedict-dir DIR] [--scope SCOPE]
                                [--human PATH] [--llm-generated PATH]
                                [--out-human PATH] [--out-full PATH]

Validates inputs always; validates assembled outputs when both --out-*
paths are given. Exits 1 with named reasons on any violation.
Scope defaults to the pair-level superset over the snapshot directory
(fail loudly); --scope latest checks the newest snapshot alone and
demotes mismatches to advisory warnings (exit stays 0), and filters the
assembled-full expectations to latest-valid LLM records.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..languages import resolve_paths
from ..parser.json import record_glosses
from ..validation import check_outputs, validate_inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True,
                        help="target dictionary language code (see dictionaries/)")
    parser.add_argument("--base", default=None,
                        help="base dictionary file (default: dictionaries/<language>/data/…)")
    parser.add_argument("--cc-cedict", default=None,
                        help="CC-CEDICT file (overrides the snapshot directory)")
    parser.add_argument("--cc-cedict-dir", default=None,
                        help="CC-CEDICT snapshot directory (default: dictionaries/cc-cedict/)")
    parser.add_argument("--scope", default="superscope",
                        choices=("superscope", "latest"),
                        help="superset scope (fail loudly) or newest snapshot alone (advisory warnings)")
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
            cc_cedict_dir=args.cc_cedict_dir,
            human=args.human, llm_generated=args.llm_generated,
        )
    except (ValueError, OSError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    try:
        report, data = validate_inputs(
            paths.base, paths.cc_cedict, paths.human, paths.llm_generated,
            cc_cedict_dir=None if args.cc_cedict else paths.cc_cedict_dir,
            scope=args.scope,
        )
    except ValueError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    out_human = args.out_human
    if data is not None and (out_human or args.out_full):
        llm_ids = set(data["llm_generated"])
        if args.scope == "latest":
            # LatestFull ships only records valid against the newest
            # snapshot: same identity, same gloss set.
            cc_glosses = data["cc_glosses"]
            llm_ids = {
                key for key in llm_ids
                if key in cc_glosses
                and record_glosses(data["llm_generated"][key]) == cc_glosses[key]
            }
        check_outputs(
            out_human,
            args.out_full,
            data["base_ids"],
            data["human_ids"],
            llm_ids,
            report,
        )
    for check in report.checks:
        status = "ok  " if check.passed else "FAIL"
        detail = f" — {check.detail}" if check.detail else ""
        print(f"{status} {check.name}{detail}")
    for warning in report.warnings:
        detail = f" — {warning.detail}" if warning.detail else ""
        print(f"warn  {warning.name}{detail}")
    if not report.passed:
        print(f"validation failed: {len(report.failures())} check(s)", file=sys.stderr)
        return 1
    print("validation passed")
    return 0


