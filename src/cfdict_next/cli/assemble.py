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
from ..languages import LANGUAGES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=sorted(LANGUAGES),
                        help="target dictionary language")
    parser.add_argument("--base", default="data/cfdict.u8")
    parser.add_argument("--human", default="data/human.u8")
    parser.add_argument("--llm-generated", default="data/llm_generated.json")
    parser.add_argument("--out-human", default="output/cfdict-next-human.u8")
    parser.add_argument("--out-confident", default=None)
    parser.add_argument("--out-full", default="output/cfdict-next-full.u8")
    args = parser.parse_args(argv)

    out_human = args.out_human or args.out_confident
    if out_human is None:
        print("assembly failed: --out-human is required", file=sys.stderr)
        return 1
    try:
        human_n, full_n = assemble_files(
            args.base, args.human, args.llm_generated,
            out_human, args.out_full, args.language,
        )
    except (ValueError, OSError) as exc:
        print(f"assembly failed: {exc}", file=sys.stderr)
        return 1
    print(f"assembly done: human {human_n} entries -> {out_human}, "
          f"full {full_n} entries -> {args.out_full}")
    return 0


