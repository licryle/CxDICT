"""Validation of source data and assembled results (spec §14).

Every check fails loudly with a named reason instead of silently
overriding or discarding data. Checks:

1. base dictionary parses with zero malformed lines.
2. CC-CEDICT parses with zero malformed lines.
3. human.u8 parses with zero malformed lines; llm_generated.json loads
   (structure, identity keys).
4. No base∩human, base∩LLM, or human∩LLM overlap.
5. Every LLM record covers exactly its CC-CEDICT gloss set
   (accept/reject via assert_gloss_coverage); no LLM record may reference
   an identity outside CC-CEDICT scope. Human entries are free-form
   French (no gloss check) but must not mix hanzi pairs or pinyin:
   if CC-CEDICT knows the (traditional, simplified) pair, the human
   pinyin must be one of its observed readings; a novel pair mixing a
   known traditional with a wrong simplified (or vice versa) fails.
6. Scope information is consistent with the inputs it claims to describe.
7. Assembled outputs parse cleanly and contain exactly the expected
   identity sets (human = base+human, full = +LLM), with no
   duplicate lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser.json import LLMDataError, assert_gloss_coverage, load_llm_json
from .parser.u8 import parse_u8_file, parse_u8_line
from .scope_info import ReleaseSources, build_scope_info


@dataclass
class Check:
    """One named validation check and its outcome."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    """Outcome of a validation run."""

    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


def _parse_or_fail(path: str | Path, label: str, report: ValidationReport):
    entries, errors = parse_u8_file(path)
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        report.checks.append(
            Check(f"{label} parses", False, f"{len(errors)} malformed line(s): {preview}")
        )
        return None
    report.checks.append(Check(f"{label} parses", True, f"{len(entries)} entries"))
    return entries


def _load_or_fail(path: str | Path, label: str, report: ValidationReport):
    try:
        data = load_llm_json(path)
    except (LLMDataError, OSError) as exc:
        report.checks.append(Check(f"{label} loads", False, str(exc)))
        return None
    report.checks.append(Check(f"{label} loads", True, f"{len(data)} records"))
    return data


def check_no_overlap(
    base_ids: set[str],
    human_ids: set[str],
    llm_generated: dict[str, Any],
    report: ValidationReport,
) -> None:
    """Check 4: the three datasets are pairwise disjoint where required."""
    pairs = (
        ("base/human", set(human_ids) & base_ids),
        ("base/LLM", set(llm_generated) & base_ids),
        ("human/LLM", set(llm_generated) & set(human_ids)),
    )
    for name, overlap in pairs:
        if overlap:
            example = sorted(overlap)[0]
            report.checks.append(
                Check(
                    f"no {name} overlap",
                    False,
                    f"{len(overlap)} overlapping identit(ies), e.g. {example!r}",
                )
            )
        else:
            report.checks.append(Check(f"no {name} overlap", True))


def check_gloss_coverage(
    cc_glosses: dict[str, set[str]],
    llm_generated: dict[str, Any],
    report: ValidationReport,
) -> None:
    """Check 5: every LLM record matches its CC-CEDICT gloss set exactly."""
    problems: list[str] = []
    for key, record in llm_generated.items():
        if key not in cc_glosses:
            problems.append(f"llm_generated:{key} is outside CC-CEDICT scope")
            continue
        try:
            assert_gloss_coverage(record, cc_glosses[key])
        except LLMDataError as exc:
            problems.append(f"llm_generated:{exc}")
    if problems:
        preview = "; ".join(problems[:5])
        report.checks.append(
            Check("LLM gloss coverage", False, f"{len(problems)} problem(s): {preview}")
        )
    else:
        report.checks.append(
            Check(
                "LLM gloss coverage",
                True,
                f"{len(llm_generated)} record(s) match CC-CEDICT",
            )
        )


def check_human_hanzi_pinyin(
    human_entries: list[Any],
    cc_pair_pinyins: dict[tuple[str, str], set[str]],
    cc_trad_to_simp: dict[str, set[str]],
    cc_simp_to_trad: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    """Check 5b: human hanzi pairs and pinyin must agree with CC-CEDICT.

    No gloss check. Rules per human entry (traditional, simplified, pinyin):
    - If the exact (trad, simp) pair exists in CC-CEDICT, pinyin must be
      one of its observed readings.
    - If the pair is novel but both sides are unseen in CC-CEDICT, allow
      (genuinely new word).
    - If the pair is novel yet trad is known with other simp, or simp is
      known with other trad, fail (mixed hanzi pair).
    """
    problems: list[str] = []
    for entry in human_entries:
        pair = (entry.traditional, entry.simplified)
        if pair in cc_pair_pinyins:
            if entry.pinyin.strip() not in cc_pair_pinyins[pair]:
                problems.append(
                    f"human:{entry.lexical_id()} has pinyin "
                    f"{entry.pinyin.strip()!r}, expected one of "
                    f"{sorted(cc_pair_pinyins[pair])}"
                )
            continue
        trad_known = pair[0] in cc_trad_to_simp
        simp_known = pair[1] in cc_simp_to_trad
        if not trad_known and not simp_known:
            continue
        problems.append(
            f"human:{entry.lexical_id()} mixes hanzi pair "
            f"({pair[0]!r}, {pair[1]!r}) unseen together in CC-CEDICT"
        )
    if problems:
        preview = "; ".join(problems[:5])
        report.checks.append(
            Check(
                "human hanzi/pinyin",
                False,
                f"{len(problems)} problem(s): {preview}",
            )
        )
    else:
        report.checks.append(
            Check(
                "human hanzi/pinyin",
                True,
                f"{len(human_entries)} entr(ies) consistent with CC-CEDICT",
            )
        )


def check_scope_info(
    info: dict[str, Any], sources: ReleaseSources, report: ValidationReport
) -> None:
    """Check 6: scope information matches the inputs it describes."""
    expected = build_scope_info(sources, generated_at=info.get("generated_at"))
    if info == expected:
        report.checks.append(Check("scope info consistent", True))
    else:
        report.checks.append(
            Check("scope info consistent", False, "figures differ from recomputation")
        )


def check_outputs(
    human_u8: str | Path,
    full_u8: str | Path,
    base_ids: set[str],
    human_ids: set[str],
    llm_ids: set[str],
    report: ValidationReport,
) -> None:
    """Check 7: assembled outputs contain exactly the expected identities."""
    for label, path, expected in (
        ("human output", human_u8, base_ids | human_ids),
        ("full output", full_u8, base_ids | human_ids | llm_ids),
    ):
        ids: list[str] = []
        try:
            with open(path, encoding="utf-8") as f:
                raw_lines = list(f)
        except OSError as exc:
            report.checks.append(Check(f"{label} parses", False, f"{path}: {exc}"))
            continue
        bad: list[str] = []
        for lineno, raw in enumerate(raw_lines, start=1):
            try:
                entry = parse_u8_line(raw)
            except ValueError as exc:
                bad.append(f"line {lineno}: {exc}")
                continue
            if entry is None:
                continue
            ids.append(entry.lexical_id())
        if bad:
            report.checks.append(
                Check(
                    f"{label} parses",
                    False,
                    f"{len(bad)} malformed line(s): " + "; ".join(bad[:3]),
                )
            )
            continue
        report.checks.append(Check(f"{label} parses", True))
        if len(set(ids)) != len(ids):
            report.checks.append(
                Check(
                    f"{label} has no duplicates",
                    False,
                    f"{len(ids) - len(set(ids))} duplicate line(s)",
                )
            )
            continue
        report.checks.append(Check(f"{label} has no duplicates", True))
        missing = expected - set(ids)
        extra = set(ids) - expected
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"missing {len(missing)}, e.g. {sorted(missing)[0]!r}")
            if extra:
                detail.append(f"unexpected {len(extra)}, e.g. {sorted(extra)[0]!r}")
            report.checks.append(
                Check(f"{label} content", False, "; ".join(detail))
            )
        else:
            report.checks.append(
                Check(f"{label} content", True, f"{len(ids)} entries as expected")
            )


def validate_inputs(
    base_path: str | Path | None,
    cc_cedict_path: str | Path,
    human_path: str | Path,
    llm_generated_path: str | Path,
) -> tuple[ValidationReport, dict[str, Any] | None]:
    """Validate all release inputs; return (report, loaded data or None)."""
    report = ValidationReport()
    if base_path is None:
        # Languages without an authoritative base: vacuous pass, zero entries.
        report.checks.append(Check("base parses", True, "no base dictionary"))
        base_entries: list = []
    else:
        base_entries = _parse_or_fail(base_path, "base", report)
    cc_entries = _parse_or_fail(cc_cedict_path, "CC-CEDICT", report)
    human_entries = _parse_or_fail(human_path, "human.u8", report)
    llm_generated = _load_or_fail(llm_generated_path, "llm_generated.json", report)
    if None in (base_entries, cc_entries, human_entries, llm_generated):
        return report, None
    assert base_entries is not None and cc_entries is not None
    assert human_entries is not None and llm_generated is not None
    base_ids = {e.lexical_id() for e in base_entries}
    human_ids = {e.lexical_id() for e in human_entries}
    cc_glosses: dict[str, set[str]] = {}
    cc_pair_pinyins: dict[tuple[str, str], set[str]] = {}
    cc_trad_to_simp: dict[str, set[str]] = {}
    cc_simp_to_trad: dict[str, set[str]] = {}
    for e in cc_entries:
        cc_glosses.setdefault(e.lexical_id(), set()).update(e.definitions)
        cc_pair_pinyins.setdefault(
            (e.traditional, e.simplified), set()
        ).add(e.pinyin.strip())
        cc_trad_to_simp.setdefault(e.traditional, set()).add(e.simplified)
        cc_simp_to_trad.setdefault(e.simplified, set()).add(e.traditional)
    check_no_overlap(base_ids, human_ids, llm_generated, report)
    check_gloss_coverage(cc_glosses, llm_generated, report)
    check_human_hanzi_pinyin(
        human_entries,
        cc_pair_pinyins,
        cc_trad_to_simp,
        cc_simp_to_trad,
        report,
    )
    return report, {
        "base_ids": base_ids,
        "human_ids": human_ids,
        "cc_glosses": cc_glosses,
        "llm_generated": llm_generated,
    }
