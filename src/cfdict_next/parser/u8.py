"""Parser for the CEDICT dictionary line format (.u8 files).

Used for authoritative base dictionaries, human curation, CC-CEDICT,
and assembled outputs alike: all share the line format

    traditional simplified [pinyin] /gloss1/gloss2/.../

Lines starting with `#` are comments/metadata; blank lines are ignored.

Known data quirks handled here:
- CC-CEDICT MDBG snapshots use CRLF line endings; `\r` is stripped.
- Definitions are separated by `/`; an embedded `/` inside a gloss cannot
  be distinguished from a separator and will split that gloss (format
  ambiguity inherent to CEDICT; tolerable, occurrences are rare).
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True)
class DictionaryEntry:
    """A single CEDICT-format dictionary entry."""

    traditional: str
    simplified: str
    pinyin: str
    definitions: tuple[str, ...]

    def lexical_id(self) -> str:
        """Deterministic identity: traditional + simplified + pinyin (spec §15)."""
        from ..identity import compute_lexical_identity

        return compute_lexical_identity(self.traditional, self.simplified, self.pinyin)


def parse_u8_line(line: str) -> Optional[DictionaryEntry]:
    """Parse one CEDICT-format line.

    Returns None for blank lines and `#` comments.
    Raises ValueError for a malformed entry line.
    """
    line = line.rstrip("\r\n").strip()
    if not line or line.startswith("#"):
        return None

    # Split off the head: "traditional simplified [pinyin] "
    bracket_end = line.find("]")
    if bracket_end == -1:
        raise ValueError(f"missing [pinyin] bracket: {line!r}")
    # Head: "traditional simplified [pinyin]" — pinyin may contain spaces.
    # Anchor on the '[' that opens the pinyin; require exactly two head tokens
    # so a missing traditional/simplified field cannot silently mis-parse.
    bracket_start = line.rfind("[", 0, bracket_end)
    if bracket_start == -1:
        raise ValueError(f"missing [pinyin] bracket: {line!r}")
    head = line[:bracket_start].strip()
    # Fields are separated by ASCII whitespace (space/tab) only: U+3000
    # (ideographic space) occurs *inside* headwords in real dictionaries
    # and must be preserved, so the split class is exactly [ \t].
    head_tokens = [t for t in re.split(r"[ \t]+", head) if t]
    if len(head_tokens) != 2:
        raise ValueError(
            f"expected exactly 'traditional simplified [pinyin]': {line!r}"
        )
    traditional, simplified = head_tokens
    pinyin = line[bracket_start + 1 : bracket_end].strip()
    
    # Normalize U+3000 to ASCII space for processing
    traditional = traditional.replace("\u3000", " ")
    simplified = simplified.replace("\u3000", " ")
    
    if not traditional or not simplified or not pinyin:
        raise ValueError(f"empty head field: {line!r}")
    
    # Definitions: everything between the first '/' and the last '/'.
    rest = line[bracket_end + 1 :].strip()
    if not rest.startswith("/"):
        raise ValueError(f"missing leading '/' of definitions: {line!r}")
    if not rest.endswith("/"):
        raise ValueError(f"missing trailing '/' of definitions: {line!r}")
    inner = rest[1:-1]
    definitions = tuple(d for d in (g.strip() for g in inner.split("/")) if d)
    if not definitions:
        raise ValueError(f"no definitions: {line!r}")
    
    return DictionaryEntry(
        traditional=traditional,
        simplified=simplified,
        pinyin=pinyin,
        definitions=definitions,
    )


def iter_u8_lines(path: str | Path) -> Iterator[str]:
    """Yield raw lines from a .u8 file, transparently handling gzip."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        yield from f


def parse_u8_file(path: str | Path) -> tuple[list[DictionaryEntry], list[tuple[int, str]]]:
    """Parse a whole .u8 file.

    Returns (entries, errors) where errors is a list of (line_number, message).
    Parsing never silently drops malformed entry lines (spec §14): malformed
    lines are reported as errors and it is the caller's job to fail.
    """
    entries_by_id: dict[str, DictionaryEntry] = {}
    errors: list[tuple[int, str]] = []
    for lineno, raw in enumerate(iter_u8_lines(path), start=1):
        try:
            entry = parse_u8_line(raw)
        except ValueError as exc:
            errors.append((lineno, str(exc)))
            continue
        if entry is None:
            continue
        
        # Merge duplicates by lexical identity
        entry_id = entry.lexical_id()
        if entry_id in entries_by_id:
            # Merge definitions: keep all unique glosses
            existing = entries_by_id[entry_id]
            merged_defs = tuple(sorted(set(existing.definitions + entry.definitions)))
            entries_by_id[entry_id] = DictionaryEntry(
                traditional=existing.traditional,
                simplified=existing.simplified,
                pinyin=existing.pinyin,
                definitions=merged_defs,
            )
        else:
            entries_by_id[entry_id] = entry
    
    return list(entries_by_id.values()), errors
