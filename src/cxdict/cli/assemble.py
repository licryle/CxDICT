"""Assembly CLI: build the human and full .u8 dictionaries (spec §10).

Usage:
    python scripts/assemble.py --language CODE [--base PATH] [--human PATH]
                                [--llm-generated PATH] [--cc-cedict PATH]
                                [--cc-cedict-dir DIR] [--scope SCOPE]
                                [--out-human PATH] [--out-full PATH]

Inputs must already satisfy the precedence rules (run scripts/cleanup.py
and validation first): any base∩human, base∩LLM or human∩LLM overlap
fails the run instead of silently overriding (spec §14).
Scope defaults to the full superset; --scope latest ships only LLM
records valid against the newest snapshot (base and human rows are
unfiltered in both modes, so the Human dictionary is scope-free).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..assembly import assemble_files
from ..languages import get_language, resolve_paths
from ..superset import load_scope_base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--language", required=True,
                        help="target dictionary language code (see dictionaries/)")
    parser.add_argument("--base", default=None,
                        help="base dictionary file (default: dictionaries/<language>/data/…)")
    parser.add_argument("--human", default=None,
                        help="human curation file (default: dictionaries/<language>/data/human.u8)")
    parser.add_argument("--llm-generated", default=None,
                        help="LLM dataset file (default: dictionaries/<language>/data/llm_generated.json)")
    parser.add_argument("--cc-cedict", default=None,
                        help="newest-snapshot file for --scope latest (default: resolved snapshot directory)")
    parser.add_argument("--cc-cedict-dir", default=None,
                        help="CC-CEDICT snapshot directory (default: dictionaries/cc-cedict/)")
    parser.add_argument("--scope", default="superscope",
                        choices=("superscope", "latest"),
                        help="ship all LLM records or only newest-valid ones")
    parser.add_argument("--out-human", default=None,
                        help="human dictionary output (default: output/<language>/…)")
    parser.add_argument("--out-full", default=None,
                        help="full dictionary output (default: output/<language>/…)")
    parser.add_argument("--skip-human", action="store_true",
                        help="omit the Human write (scope-free bytes; only needed once)")
    args = parser.parse_args(argv)
    try:
        cfg = get_language(args.language)
        paths = resolve_paths(
            args.language, base=args.base, human=args.human,
            llm_generated=args.llm_generated, cc_cedict=args.cc_cedict,
            cc_cedict_dir=args.cc_cedict_dir, out_human=args.out_human,
            out_full=args.out_full,
        )
        if cfg.scope_as_base and args.base:
            raise ValueError("scope-built base conflicts with --base")
    except (ValueError, OSError) as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 1

    try:
        scope_base = (
            load_scope_base(args.cc_cedict, paths.cc_cedict_dir, args.scope)
            if cfg.scope_as_base
            else None
        )
        human_n, full_n = assemble_files(
            paths.base, paths.human, paths.llm_generated,
            paths.out_human, paths.out_full, args.language,
            scope=args.scope, latest_cc_path=paths.cc_cedict,
            skip_human=args.skip_human,
            scope_base_entries=scope_base,
        )
    except (ValueError, OSError) as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 1
    if args.skip_human:
        print(f"assembly done: full {full_n} entries -> {paths.out_full}")
    else:
        print(f"assembly done: human {human_n} entries -> {paths.out_human}, "
              f"full {full_n} entries -> {paths.out_full}")
    return 0


