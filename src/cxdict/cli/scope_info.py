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


from . import ensure_utf8_output
from ..languages import get_language, resolve_paths
from ..parser.json import load_llm_json
from ..parser.u8 import parse_u8_file
from ..scope_info import (
    render_release_notes,
    scope_base_version,
    sha256_file,
)
from ..snapshots import version_for_snapshot_file
from ..superset import resolve_scope


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_output()
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
                        help="CC-CEDICT file (overrides the snapshot directory)")
    parser.add_argument("--cc-cedict-dir", default=None,
                        help="CC-CEDICT snapshot directory (default: dictionaries/cc-cedict/)")
    parser.add_argument("--cc-cedict-version", default=None)
    parser.add_argument("--base-version", default=None)
    parser.add_argument("--human-version", default=None)
    parser.add_argument("--llm-generated-version", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    try:
        cfg = get_language(args.language)
        base_label = cfg.base_label
        release_name = cfg.release_name
        paths = resolve_paths(
            args.language, base=args.base, human=args.human,
            llm_generated=args.llm_generated, cc_cedict=args.cc_cedict,
            cc_cedict_dir=args.cc_cedict_dir,
        )
        if cfg.scope_as_base and args.base:
            raise ValueError("scope-built base conflicts with --base")
    except (ValueError, OSError) as exc:
        print(f"scope info failed: {exc}", file=sys.stderr)
        return 1

    try:
        if args.cc_cedict:
            cc_entries, errors = parse_u8_file(paths.cc_cedict)
            if errors:
                preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
                raise ValueError(f"CC-CEDICT has {len(errors)} malformed line(s): {preview}")
            latest_entries = cc_entries
            latest_version = (
                args.cc_cedict_version or version_for_snapshot_file(paths.cc_cedict)
            )
            reference: list[tuple[str, int]] = [(latest_version, len(cc_entries))]
        else:
            resolved = resolve_scope(paths.cc_cedict_dir)
            cc_entries = resolved.entries
            latest_entries = resolved.latest_entries
            latest_version = resolved.labels["latest"]
            reference = resolved.reference
        human_entries, human_errors = parse_u8_file(paths.human)
        if human_errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
            raise ValueError(
                f"human.u8 has {len(human_errors)} malformed line(s): {preview}"
            )
        llm_generated = load_llm_json(paths.llm_generated)
        if cfg.scope_as_base:
            # Notes always describe the full scope: the union rows, which
            # this CLI resolves as its scope entries in every mode.
            base_entries = cc_entries
        elif paths.base is None:
            base_entries = []
        else:
            base_entries, errors = parse_u8_file(paths.base)
            if errors:
                preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
                raise ValueError(f"base dictionary has {len(errors)} malformed line(s): {preview}")
    except (ValueError, OSError) as exc:
        print(f"scope info failed: {exc}", file=sys.stderr)
        return 1

    try:
        if cfg.scope_as_base:
            base_version = args.base_version or scope_base_version(base_entries)
        else:
            base_version = args.base_version or (
                sha256_file(paths.base) if paths.base else "n/a"
            )
        human_version = args.human_version or sha256_file(paths.human)
        llm_generated_version = (
            args.llm_generated_version or sha256_file(paths.llm_generated)
        )
        markdown = render_release_notes(
            cc_entries,
            latest_entries,
            base_entries,
            human_entries,
            llm_generated,
            versions={
                "cc": args.cc_cedict_version or latest_version,
                "latest": latest_version,
                "base": base_version,
                "human": human_version,
                "llm": llm_generated_version,
            },
            reference=reference,
            base_label=base_label,
            release_name=release_name,
            generation_enabled=cfg.generate,
            latest_base_ids=(
                {e.lexical_id() for e in latest_entries}
                if cfg.scope_as_base
                else None
            ),
        )
    except (ValueError, OSError) as exc:
        print(f"scope info failed: {exc}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


