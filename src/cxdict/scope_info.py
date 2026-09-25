"""Release scope information (spec §12, §16).

Each release describes its source and resulting coverage: the CC-CEDICT
scope, the contributions of the authoritative base / human curation / LLM
data, and the two assembled dictionaries. Every figure derives from
the exact inputs of that release — versions are content hashes unless the
caller supplies explicit labels — so a release is traceable to the source
data that produced it.

The rendered markdown is the release-notes body consumed by the GitHub
workflow (Phase 10). No separate scope.json artifact is produced (§12).
Coverage counts reuse src/scope.py so scope info can never disagree with
the scope computation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scope import compute_scope_statistics


@dataclass(frozen=True)
class ReleaseSources:
    """Everything a release is traceable to."""

    cc_cedict_version: str
    cc_cedict_ids: set[str] = field(default_factory=set)
    base_version: str = ""
    base_ids: set[str] = field(default_factory=set)
    human_version: str = ""
    human_ids: set[str] = field(default_factory=set)
    llm_generated_version: str = ""
    llm_generated_ids: set[str] = field(default_factory=set)
    llm_models: tuple[str, ...] = ()
    prompt_versions: tuple[str, ...] = ()


def sha256_file(path: str | Path) -> str:
    """Short content hash identifying the exact bytes of a source file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()[:12]


def collect_llm_provenance(
    records: dict[str, dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Distinct (llm_model, prompt_version) values across LLM records."""
    models = sorted({r.get("llm_model", "") for r in records.values()} - {""})
    prompts = sorted({r.get("prompt_version", "") for r in records.values()} - {""})
    return tuple(models), tuple(prompts)


def build_scope_info(
    sources: ReleaseSources, generated_at: str | None = None
) -> dict[str, Any]:
    """Build the scope information dict for one release."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    statistics = compute_scope_statistics(
        sources.cc_cedict_ids,
        sources.base_ids,
        sources.human_ids,
        sources.llm_generated_ids,
    )
    return {
        "generated_at": generated_at,
        "sources": {
            "cc_cedict": {
                "version": sources.cc_cedict_version,
                "entries": statistics["cc_cedict_total"],
            },
            "base": {
                "version": sources.base_version,
                "entries": statistics["base_total"],
            },
            "human": {
                "version": sources.human_version,
                "entries": statistics["human_total"],
            },
            "llm_generated": {
                "version": sources.llm_generated_version,
                "entries": statistics["llm_generated_total"],
            },
        },
        "provenance": {
            "llm_models": list(sources.llm_models),
            "prompt_versions": list(sources.prompt_versions),
        },
        "coverage": statistics,
    }


def _in_cell(in_count: int, ref_total: int) -> str:
    """Format an 'In CC-CEDICT' cell as `N (P%)`, guarding div-by-zero."""
    if ref_total > 0:
        return f"{in_count} ({in_count / ref_total * 100:.1f}%)"
    return f"{in_count} (n/a)"


def render_scope_markdown(
    info: dict[str, Any], base_label: str, release_name: str | None = None
) -> str:
    """Render scope information as the release-notes body.

    `base_label` names the authoritative base row from the language
    registry; `release_name` names the `CxDICT-<Name>-Human/Full` output
    rows (defaults to `base_label` so older callers keep working).

    Only Coverage / Outputs / Provenance are rendered — source versions
    and generation timestamps are intentionally omitted from the notes.
    """
    coverage = info["coverage"]
    provenance = info["provenance"]
    name = release_name or base_label
    ref_total = coverage["cc_cedict_total"]

    def _row(label: str, total: int, in_cc: int) -> str:
        return f"| {label} | {total} | {_in_cell(in_cc, ref_total)} | {total - in_cc} |"

    lines = [
        "## Coverage",
        "",
        "| Category | Total | In CC-CEDICT (% of Ref) | Out of CC-CEDICT |",
        "| --- | --- | --- | --- |",
        f"| CC-CEDICT Reference | {ref_total} | - | - |",
        _row(
            f"{base_label} (authoritative)",
            coverage["base_total"],
            coverage["base_covers_cc_cedict"],
        ),
        _row(
            "Human (curated)",
            coverage["human_total"],
            coverage["human_covers_cc_cedict"],
        ),
        _row(
            "LLM generated",
            coverage["llm_generated_total"],
            coverage["llm_covers_cc_cedict"],
        ),
        "",
        f"- Missing scope (still to generate): {coverage['missing_scope_total']}",
        "",
        "## Outputs",
        "",
        "| Output | Total | In CC-CEDICT (% of Ref) | Out of CC-CEDICT |",
        "| --- | --- | --- | --- |",
        _row(
            f"CxDICT-{name}-Human",
            coverage["human_dictionary_total"],
            coverage["human_dictionary_covers_cc_cedict"],
        ),
        _row(
            f"CxDICT-{name}-Full",
            coverage["full_dictionary_total"],
            coverage["full_dictionary_covers_cc_cedict"],
        ),
        "",
        "## Provenance",
        "",
        f"- LLM models: {', '.join(provenance['llm_models']) or 'n/a'}",
        f"- Prompt versions: {', '.join(provenance['prompt_versions']) or 'n/a'}",
        "",
    ]
    return "\n".join(lines)
