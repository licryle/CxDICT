"""Superset scope over stacked CC-CEDICT snapshots (rule 1).

The superset unions all logged snapshots at (traditional, simplified) pair
level, newest wins: every row of the newest snapshot is kept, and each
older snapshot contributes only pairs absent from all newer ones. A pair
present in the newest snapshot therefore keeps exactly the newest rows —
including when upstream drops a secondary reading of a surviving pair.

Output order is deterministic: newest-snapshot file order first, then
retired pairs layer by layer (newer layers first), each in its own file
order. Every superset row remembers its newest-holder snapshot date for
per-version contribution reporting (the CC-CEDICT Reference section).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .parser.u8 import DictionaryEntry, parse_u8_file
from .snapshots import load_manifest


@dataclass(frozen=True)
class Superset:
    """One built superset scope."""

    entries: list[DictionaryEntry]
    holder: dict[str, str] = field(default_factory=dict)
    pair_holder: dict[tuple[str, str], str] = field(default_factory=dict)
    # holder: lexical identity -> newest-holder snapshot date.
    # pair_holder: (traditional, simplified) -> newest-holder snapshot date.


def build_superset(layers: list[tuple[str, list[DictionaryEntry]]]) -> Superset:
    """Union snapshot layers newest-first at pair level, newest rows win.

    ``layers`` is [(version_date, entries)] with the newest snapshot first.
    """
    entries: list[DictionaryEntry] = []
    holder: dict[str, str] = {}
    pair_holder: dict[tuple[str, str], str] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for date, layer_entries in layers:
        # Pairs met in a newer layer are skipped wholesale; every row of a
        # pair first met in this layer is kept (including polyphone
        # readings), then the whole layer's pairs are marked seen.
        for entry in layer_entries:
            pair = (entry.traditional, entry.simplified)
            if pair in seen_pairs:
                continue
            pair_holder[pair] = date
            entries.append(entry)
            holder[entry.lexical_id()] = date
        for entry in layer_entries:
            seen_pairs.add((entry.traditional, entry.simplified))
    return Superset(entries=entries, holder=holder, pair_holder=pair_holder)


def attribute_contribution(superset: Superset) -> dict[str, dict[str, int]]:
    """Per-version contribution: rows and pairs each snapshot is newest for."""
    rows: dict[str, int] = {}
    pairs: dict[str, int] = {}
    for date in superset.holder.values():
        rows[date] = rows.get(date, 0) + 1
    for date in superset.pair_holder.values():
        pairs[date] = pairs.get(date, 0) + 1
    return {
        date: {"rows": rows.get(date, 0), "pairs": pairs.get(date, 0)}
        for date in sorted(rows.keys() | pairs.keys(), reverse=True)
    }


def load_layers(cc_dir: str | Path) -> list[tuple[str, list[DictionaryEntry]]]:
    """Parse every logged snapshot newest-first; fail on malformed rows."""
    cc_dir = Path(cc_dir)
    layers = []
    for snapshot in load_manifest(cc_dir):
        entries, errors = parse_u8_file(cc_dir / snapshot.file)
        if errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
            raise ValueError(
                f"CC-CEDICT snapshot {snapshot.file} has "
                f"{len(errors)} malformed line(s): {preview}"
            )
        layers.append((snapshot.date, entries))
    return layers
