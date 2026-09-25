"""Deterministic lexical entry identity (specification §15).

Identity = traditional + simplified + pinyin. This distinguishes entries
that share characters but differ in pronunciation. Individual English
glosses are tracked at the record level (see src/parser/json.py), not in
the identity itself.
"""

from __future__ import annotations

SEP = "|"


def compute_lexical_identity(traditional: str, simplified: str, pinyin: str) -> str:
    """Return the stable identity string for one lexical entry.

    Pinyin may be an empty string for identity purposes, but traditional and
    simplified must be non-empty. Inputs are stripped; identity is therefore
    insensitive to surrounding whitespace but otherwise verbatim (tone
    numbering included) so it round-trips exactly against source files.
    """
    traditional = traditional.strip()
    simplified = simplified.strip()
    pinyin = pinyin.strip()
    if not traditional:
        raise ValueError("traditional form must not be empty")
    if not simplified:
        raise ValueError("simplified form must not be empty")
    return f"{traditional}{SEP}{simplified}{SEP}{pinyin}"


def parse_lexical_identity(identity: str) -> tuple[str, str, str]:
    """Inverse of compute_lexical_identity (identities never contain '|')."""
    parts = identity.split(SEP)
    if len(parts) != 3:
        raise ValueError(f"invalid identity: {identity!r}")
    return parts[0], parts[1], parts[2]
