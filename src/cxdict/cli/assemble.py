"""Assembly CLI: build the human and full .u8 dictionaries (spec §10).

Usage:
    python scripts/assemble.py --language CODE [--base PATH] [--human PATH]
                                [--llm-generated PATH]
                                [--out-human PATH] [--out-full PATH]

Inputs must already satisfy the precedence rules (run scripts/cleanup.py
and validation first): any base∩human, base∩LLM or human∩LLM overlap
fails the run instead of silently overriding (spec §14).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..assembly import assemble_files
from ..languages import resolve_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True,
                        help="target dictionary language code (see assets/)")
    parser.add_argument("--base", default=None,
                        help="base dictionary file (default: data/<language>/…)")
    parser.add_argument("--human", default=None,
                        help="human curation file (default: data/<language>/human.u8)")
    parser.add_argument("--llm-generated", default=None,
                        help="LLM dataset file (default: data/<language>/llm_generated.json)")
    parser.add_argument("--out-human", default=None,
                        help="human dictionary output (default: output/<language>/…)")
    parser.add_argument("--out-full", default=None,
                        help="full dictionary output (default: output/<language>/…)")
    args = parser.parse_args(argv)
    try:
        paths = resolve_paths(
            args.language, base=args.base, human=args.human,
            llm_generated=args.llm_generated, out_human=args.out_human,
            out_full=args.out_full,
        )
    except (ValueError, OSError) as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 1

    try:
        human_n, full_n = assemble_files(
            paths.base, paths.human, paths.llm_generated,
            paths.out_human, paths.out_full, args.language,
        )
    except (ValueError, OSError) as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 1
    print(f"assembly done: human {human_n} entries -> {paths.out_human}, "
          f"full {full_n} entries -> {paths.out_full}")
    return 0


