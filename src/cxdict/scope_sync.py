"""Rule-3 pruning: LLM records must match the superset scope (rules 1+3).

A record is invalid when, against the superset's canonical rows (pair-level
newest-wins):

* its (traditional, simplified) pair is absent from every snapshot,
* its pinyin is not among the superset's readings for the pair, or
* its gloss set differs from the superset row for its full identity.

Pruning is a pure function of the current snapshots plus the current
datasets — no history is consulted, so no migration is ever needed; the
per-record cc_cedict_version stamp is informational and never rewritten.
Human entries are free-form (no gloss check): mismatches there are
warnings, never deletions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .identity import parse_lexical_identity
from .parser.json import load_llm_json, record_glosses
from .parser.u8 import DictionaryEntry, parse_u8_file

#: Refuse --apply when deletions exceed this fraction of a file unless
#: --force is given (insurance against a corrupt snapshot wiping a dataset).
FORCE_THRESHOLD = 0.03


@dataclass(frozen=True)
class InvalidRecord:
    """One LLM record failing rule 3."""

    key: str
    category: str  # "pair_missing" | "pinyin_invalid" | "gloss_mismatch"
    detail: str


@dataclass(frozen=True)
class HumanWarning:
    """One human entry outside superset scope (warn-only, never deleted)."""

    key: str
    category: str  # "pair_missing" | "pinyin_invalid"
    detail: str


@dataclass
class LanguageSyncReport:
    """Outcome of reconciling one language's datasets with the superset."""

    code: str
    llm_total: int = 0
    invalid: list[InvalidRecord] = field(default_factory=list)
    human_warnings: list[HumanWarning] = field(default_factory=list)
    pruned: bool = False
    refused: str = ""


def compare_pair_scopes(
    old_entries: list[DictionaryEntry], new_entries: list[DictionaryEntry]
) -> dict[str, int]:
    """Pair-level diff between two entry lists.

    A pair counts as changed when its row set differs — different pinyin,
    different glosses, or both. Counts are disjoint and cover every pair
    on either side. Used for change summaries, never for validity itself.
    """

    def keyed(entries: list[DictionaryEntry]) -> dict[tuple[str, str], set]:
        index: dict[tuple[str, str], set] = defaultdict(set)
        for entry in entries:
            index[(entry.traditional, entry.simplified)].add(
                (entry.pinyin, tuple(sorted(entry.definitions)))
            )
        return index

    old_index = keyed(old_entries)
    new_index = keyed(new_entries)
    return {
        "new_pairs": sum(1 for p in new_index if p not in old_index),
        "retired_pairs": sum(1 for p in old_index if p not in new_index),
        "changed_pairs": sum(
            1 for p in old_index if p in new_index and old_index[p] != new_index[p]
        ),
        "identical_pairs": sum(
            1 for p in old_index if p in new_index and old_index[p] == new_index[p]
        ),
    }


def find_invalid_llm(
    superset_entries: list[DictionaryEntry],
    llm_generated: dict[str, dict[str, Any]],
) -> list[InvalidRecord]:
    """Every LLM record violating rule 3, in sorted key order."""
    readings: dict[tuple[str, str], set[str]] = defaultdict(set)
    glosses: dict[str, frozenset[str]] = {}
    for entry in superset_entries:
        readings[(entry.traditional, entry.simplified)].add(entry.pinyin)
        glosses[entry.lexical_id()] = frozenset(entry.definitions)
    invalid = []
    for key in sorted(llm_generated):
        trad, simp, pin = parse_lexical_identity(key)
        pair = (trad, simp)
        if pair not in readings:
            invalid.append(
                InvalidRecord(key, "pair_missing", "pair in no logged snapshot")
            )
        elif pin not in readings[pair]:
            invalid.append(
                InvalidRecord(
                    key, "pinyin_invalid",
                    f"pinyin {pin!r} not in superset readings "
                    f"{sorted(readings[pair])}",
                )
            )
        elif record_glosses(llm_generated[key]) != glosses[key]:
            invalid.append(
                InvalidRecord(key, "gloss_mismatch", "gloss set differs from superset row")
            )
    return invalid


def find_human_warnings(
    superset_entries: list[DictionaryEntry],
    human_entries: list[DictionaryEntry],
) -> list[HumanWarning]:
    """Human entries outside superset scope (no gloss check — free-form)."""
    readings: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in superset_entries:
        readings[(entry.traditional, entry.simplified)].add(entry.pinyin)
    warnings = []
    for entry in human_entries:
        pair = (entry.traditional, entry.simplified)
        if pair not in readings:
            warnings.append(
                HumanWarning(
                    entry.lexical_id(), "pair_missing", "pair in no logged snapshot"
                )
            )
        elif entry.pinyin.strip() not in readings[pair]:
            warnings.append(
                HumanWarning(
                    entry.lexical_id(), "pinyin_invalid",
                    f"pinyin {entry.pinyin.strip()!r} not in superset readings "
                    f"{sorted(readings[pair])}",
                )
            )
    return warnings


def sync_language_files(
    superset_entries: list[DictionaryEntry],
    human_path: str | Path,
    llm_generated_path: str | Path,
    code: str = "?",
    apply: bool = False,
    force: bool = False,
) -> LanguageSyncReport:
    """Reconcile one language's datasets; rewrite the LLM file only on apply.

    Refuses to write when deletions exceed FORCE_THRESHOLD of the file
    unless force is set. Never touches human.u8.
    """
    from .generation.output import write_llm_json

    report = LanguageSyncReport(code=code)
    human_entries, human_errors = parse_u8_file(human_path)
    if human_errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
        raise ValueError(f"human.u8 has {len(human_errors)} malformed line(s): {preview}")
    llm_generated = load_llm_json(llm_generated_path)
    report.llm_total = len(llm_generated)
    report.invalid.extend(find_invalid_llm(superset_entries, llm_generated))
    report.human_warnings.extend(find_human_warnings(superset_entries, human_entries))
    if not apply or not report.invalid:
        return report
    fraction = len(report.invalid) / report.llm_total if report.llm_total else 0
    if fraction > FORCE_THRESHOLD and not force:
        report.refused = (
            f"refusing to delete {len(report.invalid)} of {report.llm_total} "
            f"records ({fraction:.1%} > {FORCE_THRESHOLD:.0%}) without --force"
        )
        return report
    doomed = {record.key for record in report.invalid}
    write_llm_json(
        llm_generated_path,
        {k: v for k, v in llm_generated.items() if k not in doomed},
    )
    report.pruned = True
    return report
