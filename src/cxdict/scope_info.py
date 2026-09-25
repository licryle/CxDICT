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


def render_scope_markdown(info: dict[str, Any], base_label: str) -> str:
    """Render scope information as the release-notes body.

    `base_label` is required (no default): it names the authoritative base
    row from the language registry.
    """
    sources = info["sources"]
    coverage = info["coverage"]
    provenance = info["provenance"]
    lines = [
        "## Scope",
        "",
        f"Generated at {info['generated_at']}.",
        "",
        "| source | version | entries |",
        "| --- | --- | --- |",
        f"| CC-CEDICT (scope) | {sources['cc_cedict']['version']} "
        f"| {sources['cc_cedict']['entries']} |",
        f"| {base_label} (authoritative) | {sources['base']['version']} "
        f"| {sources['base']['entries']} |",
        f"| Human (curated) | {sources['human']['version']} "
        f"| {sources['human']['entries']} |",
        f"| LLM generated | {sources['llm_generated']['version']} "
        f"| {sources['llm_generated']['entries']} |",
        "",
        "## Coverage",
        "",
        f"- Missing scope (still to generate): {coverage['missing_scope_total']}",
        f"- Human dictionary: {coverage['human_dictionary_total']} entries",
        f"- Full dictionary: {coverage['full_dictionary_total']} entries",
        f"- {base_label} covers {coverage['base_covers_cc_cedict']} CC-CEDICT entries",
        f"- Human covers {coverage['human_covers_cc_cedict']} CC-CEDICT entries",
        f"- LLM covers {coverage['llm_covers_cc_cedict']} CC-CEDICT entries",
        "",
        "## Provenance",
        "",
        f"- LLM models: {', '.join(provenance['llm_models']) or 'n/a'}",
        f"- Prompt versions: {', '.join(provenance['prompt_versions']) or 'n/a'}",
        "",
    ]
    return "\n".join(lines)
