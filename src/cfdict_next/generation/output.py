"""Assembling generation results into the LLM dataset file (Phase 5, spec §4, §8).

Results arrive per entry (identity plus full sense list); each becomes one
record stamped with full provenance in the `llm_generated.json` mapping.
Writes are atomic (temp file + rename) so an interrupted run never leaves
a half-written dataset. Merging into an existing file refuses to overwrite
keys (spec §14: generation targets the missing scope, so collisions mean
a bug upstream).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import GenerationResult


@dataclass(frozen=True)
class Provenance:
    """Provenance stamped on every generated record (spec §8, §16)."""

    cc_cedict_version: str
    llm_model: str
    prompt_version: str


def build_records(
    results: list[GenerationResult],
    provenance: Provenance,
    generation_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Group per-entry results into an identity -> record mapping.

    `generation_date` defaults to the current UTC time in ISO 8601; pass an
    explicit value for deterministic output (tests).
    """
    if generation_date is None:
        generation_date = datetime.now(timezone.utc).isoformat()
    records: dict[str, dict[str, Any]] = {}
    for result in results:
        senses = [
            {"source_gloss": s.gloss, "definition": s.definition}
            for s in result.senses
        ]
        records[result.key] = {
            "traditional": result.traditional,
            "simplified": result.simplified,
            "pinyin": result.pinyin,
            "senses": senses,
            "cc_cedict_version": provenance.cc_cedict_version,
            "llm_model": provenance.llm_model,
            "prompt_version": provenance.prompt_version,
            "generation_date": generation_date,
        }
    return records


def merge_records(
    existing: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Merge new records into an existing dataset; refuse key overwrites."""
    collision = set(existing) & set(new)
    if collision:
        raise ValueError(
            f"refusing to overwrite {len(collision)} existing record(s), e.g. "
            f"{sorted(collision)[0]!r} — generate only the missing scope"
        )
    return {**existing, **new}


def write_llm_json(path: str | Path, data: dict[str, dict[str, Any]]) -> None:
    """Atomically write an LLM dataset file (sorted keys, UTF-8)."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)
