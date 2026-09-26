"""Rule-3 pruning CLI: reconcile LLM datasets with the superset scope.

Usage:
    python scripts/scope_sync.py [--language CODE] [--cc-cedict-dir DIR]
                                 [--apply] [--force]

Dry-run by default (prints the prune queue, writes nothing). --apply
deletes invalid LLM records; --force is required when deletions exceed 3%
of a file. Human entries are reported as warnings only, never deleted.
--language limits the run to one language; the default covers every
language unit discovered under dictionaries/ (dirs owning a dict.toml).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..languages import get_language, resolve_paths
from ..superset import build_superset, load_layers
from ..scope_sync import LanguageSyncReport, compare_pair_scopes, sync_language_files

SAMPLES = 5


def discover_languages() -> list[str]:
    """Every language unit: directories under dictionaries/ owning dict.toml."""
    codes = sorted(
        p.parent.name
        for p in Path("dictionaries").glob("*/dict.toml")
        if p.is_file()
    )
    for code in codes:
        get_language(code)  # fail loud on a broken definition
    return codes


def print_report(report: LanguageSyncReport) -> None:
    print(f"[{report.code}] llm records: {report.llm_total}, "
          f"invalid: {len(report.invalid)}")
    by_category: dict[str, int] = {}
    for record in report.invalid:
        by_category[record.category] = by_category.get(record.category, 0) + 1
    for category in ("pair_missing", "pinyin_invalid", "gloss_mismatch"):
        if by_category.get(category):
            print(f"  {category}: {by_category[category]}")
    for record in report.invalid[:SAMPLES]:
        print(f"    - {record.key} ({record.category}): {record.detail}")
    if len(report.invalid) > SAMPLES:
        print(f"    ... and {len(report.invalid) - SAMPLES} more")
    if report.human_warnings:
        print(f"  human warnings: {len(report.human_warnings)}")
        for warning in report.human_warnings[:SAMPLES]:
            print(f"    ! {warning.key} ({warning.category}): {warning.detail}")
    if report.refused:
        print(f"  REFUSED: {report.refused}", file=sys.stderr)
    elif report.pruned:
        print(f"  pruned {len(report.invalid)} record(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--language", default=None,
                        help="single language code (default: all discovered)")
    parser.add_argument("--cc-cedict-dir", default=None,
                        help="CC-CEDICT snapshot directory (default: dictionaries/cc-cedict/)")
    parser.add_argument("--apply", action="store_true",
                        help="delete invalid records (default: dry run)")
    parser.add_argument("--force", action="store_true",
                        help="allow deletions above 3%% of a file")
    args = parser.parse_args(argv)
    try:
        codes = [args.language] if args.language else discover_languages()
        if args.language:
            get_language(args.language)
        first = resolve_paths(codes[0], cc_cedict_dir=args.cc_cedict_dir)
        layers = load_layers(first.cc_cedict_dir)
    except (ValueError, OSError) as exc:
        print(f"scope sync failed: {exc}", file=sys.stderr)
        return 1
    superset = build_superset(layers)
    latest_entries = layers[0][1]
    composition = compare_pair_scopes(latest_entries, superset.entries)
    print(f"superset: {len(superset.entries)} rows over latest "
          f"(+{composition['new_pairs']} retired pairs carried, "
          f"{composition['identical_pairs']} latest pairs unchanged)")
    if not args.apply:
        print("dry run — nothing written (pass --apply to prune)")
    rc = 0
    for code in codes:
        try:
            paths = resolve_paths(code, cc_cedict_dir=args.cc_cedict_dir)
            report = sync_language_files(
                superset.entries, paths.human, paths.llm_generated,
                code=code, apply=args.apply, force=args.force,
            )
        except (ValueError, OSError) as exc:
            print(f"[{code}] scope sync failed: {exc}", file=sys.stderr)
            return 1
        print_report(report)
        if report.refused:
            rc = 1
    return rc
