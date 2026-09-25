"""Scope information CLI: describe one release's sources and coverage (spec §12).

Usage:
    python scripts/scope_info.py --language CODE [--base PATH] [--human PATH]
                                   [--llm-generated PATH]
                                   [--cc-cedict PATH] [--cc-cedict-version LABEL]
                                   [--base-version LABEL] [--human-version LABEL]
                                   [--llm-generated-version LABEL] [--out PATH]

Version labels default to content hashes of the exact input bytes, so the
output is traceable to the sources even when no explicit version is given.
Prints the release-notes markdown to stdout (or --out).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from ..languages import get_language, resolve_paths
from ..parser.json import load_llm_json
from ..parser.u8 import parse_u8_file
from ..scope_info import (
    ReleaseSources,
    build_scope_info,
    collect_llm_provenance,
    render_scope_markdown,
    sha256_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True,
                        help="target dictionary language code (see dictionaries/)")
    parser.add_argument("--base", default=None,
                        help="base dictionary file (default: dictionaries/<language>/data/…)")
    parser.add_argument("--human", default=None,
                        help="human curation file (default: dictionaries/<language>/data/human.u8)")
    parser.add_argument("--llm-generated", default=None,
                        help="LLM dataset file (default: dictionaries/<language>/data/llm_generated.json)")
    parser.add_argument("--cc-cedict", default=None,
                        help="CC-CEDICT file (default: dictionaries/cc-cedict/…)")
    parser.add_argument("--cc-cedict-version", default=None)
    parser.add_argument("--base-version", default=None)
    parser.add_argument("--human-version", default=None)
    parser.add_argument("--llm-generated-version", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    try:
        base_label = get_language(args.language).base_label
        paths = resolve_paths(
            args.language, base=args.base, human=args.human,
            llm_generated=args.llm_generated, cc_cedict=args.cc_cedict,
        )
    except (ValueError, OSError) as exc:
        print(f"scope info failed: {exc}", file=sys.stderr)
        return 1

    try:
        if paths.base is None:
            base_entries = []
        else:
            base_entries, errors = parse_u8_file(paths.base)
            if errors:
                preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
                raise ValueError(f"base dictionary has {len(errors)} malformed line(s): {preview}")
        cc_entries, errors = parse_u8_file(paths.cc_cedict)
        if errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
            raise ValueError(f"CC-CEDICT has {len(errors)} malformed line(s): {preview}")
        human_entries, human_errors = parse_u8_file(paths.human)
        if human_errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
            raise ValueError(
                f"human.u8 has {len(human_errors)} malformed line(s): {preview}"
            )
        llm_generated = load_llm_json(paths.llm_generated)
    except (ValueError, OSError) as exc:
        print(f"scope info failed: {exc}", file=sys.stderr)
        return 1

    models, prompts = collect_llm_provenance(llm_generated)
    sources = ReleaseSources(
        cc_cedict_version=args.cc_cedict_version or sha256_file(paths.cc_cedict),
        cc_cedict_ids={e.lexical_id() for e in cc_entries},
        base_version=args.base_version or (sha256_file(paths.base) if paths.base else "n/a"),
        base_ids={e.lexical_id() for e in base_entries},
        human_version=args.human_version or sha256_file(paths.human),
        human_ids={e.lexical_id() for e in human_entries},
        llm_generated_version=args.llm_generated_version
        or sha256_file(paths.llm_generated),
        llm_generated_ids=set(llm_generated),
        llm_models=models,
        prompt_versions=prompts,
    )
    markdown = render_scope_markdown(build_scope_info(sources), base_label)
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


