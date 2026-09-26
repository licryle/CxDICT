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
    # Latest-scope companions (absent = single-scope release): the newest
    # snapshot's version and identities, the LLM identities valid against
    # it (same identity, same gloss set — the exact LatestFull record set),
    # and the per-version contribution rows (label, rows) newest-first.
    latest_cc_cedict_version: str = ""
    latest_cc_cedict_ids: set[str] | None = None
    latest_llm_ids: set[str] | None = None
    reference: tuple[tuple[str, int], ...] = ()


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
    if sources.reference:
        contributed = sum(rows for _, rows in sources.reference)
        if contributed != statistics["cc_cedict_total"]:
            raise ValueError(
                f"CC-CEDICT reference rows ({contributed}) do not sum to "
                f"the scope total ({statistics['cc_cedict_total']})"
            )
    latest_statistics = None
    scope_detail: dict[str, int] = {}
    if sources.latest_cc_cedict_ids is not None:
        latest_ids = sources.latest_cc_cedict_ids
        latest_llm = (
            sources.latest_llm_ids
            if sources.latest_llm_ids is not None
            else sources.llm_generated_ids
        )
        latest_statistics = compute_scope_statistics(
            latest_ids,
            sources.base_ids,
            sources.human_ids,
            latest_llm,
        )
        full_ids = sources.base_ids | sources.human_ids | sources.llm_generated_ids
        latest_full_ids = sources.base_ids | sources.human_ids | latest_llm
        scope_detail = {
            # Cross-scope cells neither stats object has alone (all exact):
            "llm_covers_latest": len(sources.llm_generated_ids & latest_ids),
            "superfull_covers_latest": len(full_ids & latest_ids),
            "latestfull_covers_super": len(latest_full_ids & sources.cc_cedict_ids),
        }
    info: dict[str, Any] = {
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
        "reference": [
            {"label": label, "rows": rows} for label, rows in sources.reference
        ],
    }
    if latest_statistics is not None:
        info["sources"]["latest_cc_cedict"] = {
            "version": sources.latest_cc_cedict_version,
            "entries": latest_statistics["cc_cedict_total"],
        }
        info["latest_coverage"] = latest_statistics
        info["scope_detail"] = scope_detail
    return info


def _in_cell(in_count: int, ref_total: int) -> str:
    """Format an 'In CC-CEDICT' cell as `N (P%)`, guarding div-by-zero."""
    if ref_total > 0:
        return f"{in_count} ({in_count / ref_total * 100:.1f}%)"
    return f"{in_count} (n/a)"


def _out_cell(in_count: int, ref_total: int, missing_scope_total: int) -> str:
    """Format an output-row 'In CC-CEDICT' cell.

    An output can never honestly claim 100.0% while scope remains
    missing (out-of-scope extras can round it up there), so in that
    case the display is downgraded to 99.9+%.
    """
    if ref_total > 0:
        pct = f"{in_count / ref_total * 100:.1f}"
        if missing_scope_total > 0 and pct == "100.0":
            pct = "99.9+"
        return f"{in_count} ({pct}%)"
    return f"{in_count} (n/a)"


def render_scope_markdown(
    info: dict[str, Any], base_label: str, release_name: str | None = None
) -> str:
    """Render scope information as the release-notes body.

    `base_label` names the authoritative base row from the language
    registry; `release_name` names the `CxDICT-<Name>-SuperFull` output
    rows (defaults to `base_label` so older callers keep working).

    Only Scopes / Coverage / CC-CEDICT Reference / Outputs / LLM
    Generation details are rendered — source versions and generation
    timestamps are intentionally omitted from the notes. With
    latest-scope data present, both tables gain Latest-CEDICT columns;
    otherwise they use the legacy single-column layout.
    """
    coverage = info["coverage"]
    provenance = info["provenance"]
    name = release_name or base_label
    ref_total = coverage["cc_cedict_total"]
    missing = coverage["missing_scope_total"]

    def _row(label: str, total: int, in_cc: int) -> str:
        return f"| {label} | {total} | {_in_cell(in_cc, ref_total)} | {total - in_cc} |"

    def _out_row(
        label: str, total: int, in_cc: int,
        ref: int = ref_total, miss: int = missing,
    ) -> str:
        return (
            f"| {label} | {total} | "
            f"{_out_cell(in_cc, ref, miss)} | {total - in_cc} |"
        )

    lines = [
        "## Scopes",
        "",
        "- SuperFull: base + human + every LLM record — Super-CEDICT scope "
        "(all snapshots combined, retired words included).",
        "- LatestFull: base + human + only newest-valid LLM records — "
        "Latest-CEDICT scope (newest snapshot alone).",
        "- Human: base + human curation, no LLM content (scope-free).",
        "",
        "## Coverage",
        "",
    ]
    latest = info.get("latest_coverage")
    if latest is None:
        lines += [
            "| Category | Total | In CC-CEDICT (% of Ref) | Out of CC-CEDICT |",
            "| --- | --- | --- | --- |",
            f"| CC-CEDICT Reference (Under license CC BY-SA 4.0) | {ref_total} | - | - |",
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
            f"| Missing scope (still to generate) | {missing} | "
            f"{_in_cell(missing, ref_total)} | N/A |",
            "",
        ]
    else:
        latest_total = latest["cc_cedict_total"]
        latest_missing = latest["missing_scope_total"]
        detail = info.get("scope_detail", {})

        def _dual(
            label: str, total: int, in_super: int, in_latest: int,
            out_na: bool = False,
        ) -> str:
            cells = (
                f"| {label} | {total} | "
                f"{_in_cell(in_super, ref_total)} | "
                f"{_in_cell(in_latest, latest_total)} | "
            )
            if out_na:
                return cells + "N/A | N/A |"
            return cells + f"{total - in_super} | {total - in_latest} |"

        lines += [
            "| Category | Total | In Super-CEDICT (% of Ref) | "
            "In Latest-CEDICT (% of Ref) | Out of Super-CEDICT | "
            "Out of Latest-CEDICT |",
            "| --- | --- | --- | --- | --- | --- |",
            _dual(
                "CC-CEDICT Reference (Under license CC BY-SA 4.0)",
                ref_total, ref_total, latest_total,
            ),
            _dual(
                f"{base_label} (authoritative)",
                coverage["base_total"],
                coverage["base_covers_cc_cedict"],
                latest["base_covers_cc_cedict"],
            ),
            _dual(
                "Human (curated)",
                coverage["human_total"],
                coverage["human_covers_cc_cedict"],
                latest["human_covers_cc_cedict"],
            ),
            _dual(
                "LLM generated",
                coverage["llm_generated_total"],
                coverage["llm_covers_cc_cedict"],
                detail.get("llm_covers_latest", 0),
            ),
            _dual(
                "Missing scope (still to generate)",
                missing, missing, latest_missing, out_na=True,
            ),
            "",
        ]
    if info.get("reference"):
        lines += [
            "## CC-CEDICT Reference",
            "",
            f"Total CEDICT records: {ref_total}",
        ] + [
            f"CEDICT {row['label']}: {row['rows']}"
            for row in info["reference"]
        ] + [""]
    if latest is None:
        lines += [
            "## Outputs",
            "",
            "| Output | Total | In CC-CEDICT (% of Ref) | Out of CC-CEDICT |",
            "| --- | --- | --- | --- |",
            _out_row(
                f"CxDICT-{name}-Human",
                coverage["human_dictionary_total"],
                coverage["human_dictionary_covers_cc_cedict"],
            ),
            _out_row(
                f"CxDICT-{name}-SuperFull",
                coverage["full_dictionary_total"],
                coverage["full_dictionary_covers_cc_cedict"],
            ),
        ]
    else:
        latest_total = latest["cc_cedict_total"]
        latest_missing = latest["missing_scope_total"]
        detail = info.get("scope_detail", {})

        def _dual_out(
            label: str, total: int, in_super: int, in_latest: int,
        ) -> str:
            return (
                f"| {label} | {total} | "
                f"{_out_cell(in_super, ref_total, missing)} | "
                f"{_out_cell(in_latest, latest_total, latest_missing)} | "
                f"{total - in_super} | {total - in_latest} |"
            )

        lines += [
            "## Outputs",
            "",
            "| Output | Total | In Super-CEDICT (% of Ref) | "
            "In Latest-CEDICT (% of Ref) | Out of Super-CEDICT | "
            "Out of Latest-CEDICT |",
            "| --- | --- | --- | --- | --- | --- |",
            _dual_out(
                f"CxDICT-{name}-SuperFull",
                coverage["full_dictionary_total"],
                coverage["full_dictionary_covers_cc_cedict"],
                detail.get("superfull_covers_latest", 0),
            ),
            _dual_out(
                f"CxDICT-{name}-LatestFull",
                latest["full_dictionary_total"],
                detail.get("latestfull_covers_super", 0),
                latest["full_dictionary_covers_cc_cedict"],
            ),
            _dual_out(
                f"CxDICT-{name}-Human",
                coverage["human_dictionary_total"],
                coverage["human_dictionary_covers_cc_cedict"],
                latest["human_dictionary_covers_cc_cedict"],
            ),
        ]
    lines += [
        "",
        "## LLM Generation details",
        "",
        f"- LLM models: {', '.join(provenance['llm_models']) or 'n/a'}",
        f"- Prompt versions: {', '.join(provenance['prompt_versions']) or 'n/a'}",
        "",
    ]
    return "\n".join(lines)
