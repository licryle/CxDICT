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
from .snapshots import MANIFEST_FILENAME, load_manifest, snapshot_version, version_for_snapshot_file

from .languages import resolve_cc_cedict


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


def load_scope_base(
    explicit: str | Path | None = None,
    cc_dir: str | Path | None = None,
    scope: str = "superscope",
) -> list[DictionaryEntry]:
    """Scope-built base rows for scope-as-base languages (content IS scope).

    An explicit file pins the scope content (escape hatch); otherwise the
    rows come from the snapshot log — the pair-level superset, or the
    newest layer alone for scope="latest" (follows the run scope so
    latest-filtered assemblies validate). Fails loudly on bad input.
    """
    if scope not in ("superscope", "latest"):
        raise ValueError(f"unknown scope {scope!r} (want 'superscope' or 'latest')")
    if explicit is not None:
        entries, errors = parse_u8_file(explicit)
        if errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
            raise ValueError(
                f"scope base {explicit} has {len(errors)} malformed line(s): {preview}"
            )
        return entries
    if cc_dir is None:
        raise ValueError("scope-built base needs a snapshot directory or file")
    layers = load_layers(cc_dir)
    if scope == "latest":
        return layers[0][1]
    return build_superset(layers).entries


@dataclass(frozen=True)
class Scope:
    """Resolved CC-CEDICT scope for one run (directory mode).

    One construction owns what four call sites used to re-derive: the
    active rows (pair-level superset, or newest layer for scope="latest"),
    the newest rows, per-row holder dates plus per-date version labels
    (for generation stamps), display labels, per-version contribution
    rows, and the check detail line. Explicit-file mode stays a one-liner
    per caller and never touches this object.
    """

    entries: list[DictionaryEntry]
    latest_entries: list[DictionaryEntry]
    holder: dict[str, str]
    date_versions: dict[str, str]
    labels: dict[str, str]
    reference: list[tuple[str, int]]
    detail: str


def resolve_scope(cc_dir: str | Path, scope: str = "superscope") -> Scope:
    """Resolve a snapshot directory to the scope for one run.

    Manifest log present: pair-level superset (newest rows win) by
    default, newest layer alone for scope="latest". Log-less directory:
    the newest file is the whole scope. Fails loudly on bad scope or
    malformed rows (callers convert to their own check conventions).
    """
    if scope not in ("superscope", "latest"):
        raise ValueError(f"unknown scope {scope!r} (want 'superscope' or 'latest')")
    cc_dir = Path(cc_dir)
    if not (cc_dir / MANIFEST_FILENAME).is_file():
        resolved = resolve_cc_cedict(cc_dir)
        entries, errors = parse_u8_file(resolved)
        if errors:
            preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
            raise ValueError(
                f"CC-CEDICT has {len(errors)} malformed line(s): {preview}"
            )
        label = version_for_snapshot_file(resolved, cc_dir)
        return Scope(
            entries=entries,
            latest_entries=entries,
            holder={},
            date_versions={},
            labels={"cc": label, "latest": label},
            reference=[(label, len(entries))],
            detail=f"{len(entries)} entries",
        )
    layers = load_layers(cc_dir)
    snapshots = {s.date: s for s in load_manifest(cc_dir)}
    date_versions = {
        date: snapshot_version(snapshots[date]) for date, _ in layers
    }
    latest_date, latest_rows = layers[0]
    superset = build_superset(layers)
    if scope == "latest":
        entries: list[DictionaryEntry] = latest_rows
        holder: dict[str, str] = {e.lexical_id(): latest_date for e in latest_rows}
        detail = f"latest snapshot {latest_date}: {len(entries)} entries"
    else:
        entries = superset.entries
        holder = superset.holder
        detail = (
            f"superset: {len(entries)} entries from {len(layers)} snapshot(s)"
        )
    contribution = attribute_contribution(superset)
    reference = [(date, contribution[date]["rows"]) for date in contribution]
    latest_label = date_versions[latest_date]
    return Scope(
        entries=entries,
        latest_entries=latest_rows,
        holder=holder,
        date_versions=date_versions,
        labels={"cc": latest_label, "latest": latest_label},
        reference=reference,
        detail=detail,
    )
