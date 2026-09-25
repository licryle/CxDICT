"""Dictionary assembly (spec §10, §14).

Precedence:  base > human.u8 > llm_generated.json

- The human dictionary contains base + human.u8 (§10.1).
- The full dictionary additionally contains llm_generated.json (§10.2).
- Higher-priority sources always win: `assemble` *raises* on any
  base∩human, base∩LLM or human∩LLM overlap instead of silently
  overriding (§14). Run the cleanup script first so the datasets are
  proper deltas; Phase 9 validation gates the workflow before assembly
  runs.
- Output order is deterministic: base file order, then LLM-only entries
  sorted by identity — so identical inputs always yield byte-identical
  outputs.
- Headword fields split on ASCII space/tab (a single CFDICT line uses
  tabs); U+3000 inside headwords is content and round-trips exactly.
- Definitions are strip-normalized on parse (a few dozen CFDICT lines
  carry incidental separator whitespace — "/ " gaps, "//" empties,
  even non-breaking spaces); the writer therefore emits canonical
  "/"-joined definitions. Content is preserved exactly — including
  U+3000 headwords — only incidental whitespace is normalized,
  deterministically.
- The writer restores U+3000 in headwords: the parser normalizes U+3000 to
  ASCII space on read, and no surviving ASCII space inside a headword can
  be original (fields split on ASCII space), so the reversal is exact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .languages import get_language
from .parser.json import load_llm_json
from .parser.u8 import DictionaryEntry, iter_u8_lines, parse_u8_file


def format_u8_entry(entry: DictionaryEntry) -> str:
    """Serialize one entry to a CEDICT line (LF ending, U+3000 restored)."""
    traditional = entry.traditional.replace(" ", "　")
    simplified = entry.simplified.replace(" ", "　")
    definitions = "/".join(entry.definitions)
    return f"{traditional} {simplified} [{entry.pinyin}] /{definitions}/\n"


def record_to_entry(key: str, record: dict[str, Any]) -> DictionaryEntry:
    """Convert one validated LLM record to a dictionary entry."""
    return DictionaryEntry(
        traditional=record["traditional"],
        simplified=record["simplified"],
        pinyin=record["pinyin"],
        definitions=tuple(s["definition"] for s in record["senses"]),
    )


def section_header_for(code: str) -> str:
    """Base section header for one language, from the registry."""
    cfg = get_language(code)
    header = f"# {cfg.base_label} Authoritative entries"
    if cfg.base_url:
        header += f" (from {cfg.base_url})"
    return header


BASE_SECTION_HEADER = section_header_for("fr")
HUMAN_SECTION_HEADER = "# Human-curated entries (data/human.u8)"
LLM_SECTION_HEADER = "# LLM-Generated entries (data/llm_generated.json)"


def assemble_sections(
    base_entries: list[DictionaryEntry],
    human_entries: list[DictionaryEntry],
    llm_generated: dict[str, dict[str, Any]],
) -> tuple[list[DictionaryEntry], list[DictionaryEntry], list[DictionaryEntry]]:
    """Split assembly into (base, human_extra, llm_extra).

    Same overlap checks as `assemble`; the extra lists preserve output
    order (base file order, then human file order, then LLM-only
    entries sorted by identity).
    """
    base_ids = {e.lexical_id() for e in base_entries}
    human_ids = [e.lexical_id() for e in human_entries]
    if len(set(human_ids)) != len(human_ids):
        raise ValueError("human.u8 contains duplicate entries — fix the source first")
    bad_human = sorted(set(human_ids) & base_ids)
    if bad_human:
        raise ValueError(
            f"{len(bad_human)} human record(s) overlap base, e.g. "
            f"{bad_human[0]!r} — run cleanup first"
        )
    bad_llm = sorted((set(llm_generated) & base_ids) | (set(llm_generated) & set(human_ids)))
    if bad_llm:
        raise ValueError(
            f"{len(bad_llm)} LLM record(s) overlap base/human, e.g. "
            f"{bad_llm[0]!r} — run cleanup first"
        )
    llm_extra = [
        record_to_entry(key, llm_generated[key]) for key in sorted(llm_generated)
    ]
    return list(base_entries), list(human_entries), llm_extra


def assemble(
    base_entries: list[DictionaryEntry],
    human_entries: list[DictionaryEntry],
    llm_generated: dict[str, dict[str, Any]],
) -> tuple[list[DictionaryEntry], list[DictionaryEntry]]:
    """Assemble (human_entries, full_entries); raise on overlaps (§14)."""
    base, human_extra, llm_extra = assemble_sections(
        base_entries, human_entries, llm_generated
    )
    return base + human_extra, base + human_extra + llm_extra


def write_sectioned_u8_file(
    path: str | Path, sections: list[tuple[str | None, list[DictionaryEntry]]]
) -> None:
    """Atomically write a .u8 dictionary file (UTF-8, LF endings).

    Each section is an optional `#` header plus its entries. Headers are
    plain comments (the parser skips them), and sections without entries
    are omitted so no header dangles at end of file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for header, entries in sections:
            if not entries:
                continue
            if header is not None:
                f.write(header + "\n")
            for entry in entries:
                f.write(format_u8_entry(entry))
    tmp.replace(path)


def write_u8_file(path: str | Path, entries: list[DictionaryEntry]) -> None:
    """Atomically write a .u8 dictionary file (UTF-8, LF endings)."""
    write_sectioned_u8_file(path, [(None, entries)])


def assemble_files(
    base_path: str | Path | None,
    human_path: str | Path,
    llm_generated_path: str | Path,
    out_human_path: str | Path,
    out_full_path: str | Path,
    language: str,
) -> tuple[int, int]:
    """Full assembly from on-disk sources; return (human_n, full_n).

    `language` is required (no default): it selects the base section
    header. `base_path` may be None for languages without an
    authoritative base (the base section is then empty and omitted).
    """
    if base_path is None:
        entries, errors = [], []
    else:
        entries, errors = parse_u8_file(base_path)
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        raise ValueError(f"base dictionary has {len(errors)} malformed line(s): {preview}")
    human_entries, human_errors = parse_u8_file(human_path)
    if human_errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
        raise ValueError(
            f"human.u8 has {len(human_errors)} malformed line(s): {preview}"
        )
    llm_generated = load_llm_json(llm_generated_path)
    base, human_extra, llm_extra = assemble_sections(
        entries, human_entries, llm_generated
    )
    write_sectioned_u8_file(
        out_human_path,
        [
            (section_header_for(language), base),
            (HUMAN_SECTION_HEADER, human_extra),
        ],
    )
    write_sectioned_u8_file(
        out_full_path,
        [
            (section_header_for(language), base),
            (HUMAN_SECTION_HEADER, human_extra),
            (LLM_SECTION_HEADER, llm_extra),
        ],
    )
    human_n = len(base) + len(human_extra)
    return human_n, human_n + len(llm_extra)


def iter_output_lines(path: str | Path):
    """Yield entry lines of an assembled file (used by validation, Phase 9)."""
    yield from iter_u8_lines(path)
