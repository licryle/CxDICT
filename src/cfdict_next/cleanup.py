"""Cleanup: maintain human and LLM datasets as deltas over the authoritative base.

Precedence (spec §9):  base > human.u8 > llm_generated.json

Rules:
- Drop from human.u8 any entry now present in the base dictionary.
- Drop from llm_generated.json any entry now present in the base dictionary or human.u8.

Inputs are validated before use (spec §14): a malformed .u8 line or an
invalid LLM record fails the run instead of silently discarding data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parser.json import load_llm_json
from .parser.u8 import parse_u8_file


@dataclass(frozen=True)
class CleanupReport:
    """Counts describing what one cleanup run removed."""

    human_before: int
    human_removed_base: int
    human_after: int
    llm_before: int
    llm_removed_base: int
    llm_removed_human: int
    llm_after: int


def base_identities(base_path: str | Path) -> set[str]:
    """Parse the base dictionary and return its lexical identity set (fail on errors)."""
    entries, errors = parse_u8_file(base_path)
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        raise ValueError(f"base dictionary has {len(errors)} malformed line(s): {preview}")
    return {entry.lexical_id() for entry in entries}


def human_identities(human_path: str | Path) -> set[str]:
    """Parse human.u8 and return its lexical identity set (fail on errors)."""
    entries, errors = parse_u8_file(human_path)
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        raise ValueError(f"human.u8 has {len(errors)} malformed line(s): {preview}")
    return {entry.lexical_id() for entry in entries}


def cleanup_datasets(
    base_ids: set[str],
    human_ids: set[str],
    llm_generated: dict[str, dict[str, Any]],
) -> tuple[set[str], dict[str, dict[str, Any]], CleanupReport]:
    """Apply the precedence rules; return (human_kept, llm_kept, report).

    Pure function over already-loaded data — the file I/O wrapper below
    handles reading, validating, and atomically rewriting the datasets.
    Human identities are a set (raw .u8 entries); LLM data is a mapping.
    """
    human_kept = {k for k in human_ids if k not in base_ids}
    llm_kept = {
        k: v
        for k, v in llm_generated.items()
        if k not in base_ids and k not in human_kept
    }
    report = CleanupReport(
        human_before=len(human_ids),
        human_removed_base=len(human_ids) - len(human_kept),
        human_after=len(human_kept),
        llm_before=len(llm_generated),
        llm_removed_base=len([k for k in llm_generated if k in base_ids]),
        llm_removed_human=len(
            [k for k in llm_generated if k not in base_ids and k in human_kept]
        ),
        llm_after=len(llm_kept),
    )
    return human_kept, llm_kept, report


def cleanup_files(
    base_path: str | Path,
    human_path: str | Path,
    llm_generated_path: str | Path,
    dry_run: bool = False,
) -> CleanupReport:
    """Run cleanup against on-disk datasets; rewrite them unless dry_run."""
    from .assembly import write_u8_file
    from .generation.output import write_llm_json

    base_ids = base_identities(base_path)
    human_entries, human_errors = parse_u8_file(human_path)
    if human_errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
        raise ValueError(
            f"human.u8 has {len(human_errors)} malformed line(s): {preview}"
        )
    human_ids = {e.lexical_id() for e in human_entries}
    llm_generated = load_llm_json(llm_generated_path)
    human_kept, llm_kept, report = cleanup_datasets(
        base_ids, human_ids, llm_generated
    )
    if not dry_run:
        # Retain original human file order for kept entries.
        kept_entries = [e for e in human_entries if e.lexical_id() in human_kept]
        write_u8_file(human_path, kept_entries)
        write_llm_json(llm_generated_path, llm_kept)
    return report
