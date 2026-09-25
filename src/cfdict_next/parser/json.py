"""Loading and validation of the LLM dataset file (spec §4, §5, §8, §15).

File format (`llm_generated.json`): a single JSON object mapping lexical
identity -> record. JSON is the working/generation format for LLM output
(spec §4); .u8 is only used for assembled dictionaries.

One record per lexical entry. Each record carries a `senses` list with one
sense per CEDICT gloss (spec §5: generation happens per gloss; §15: glosses
are tracked per generated definition). The sense list MUST cover exactly
the CC-CEDICT gloss set for the entry — same glosses, same count
(see `assert_gloss_coverage`, the accept/reject criterion). A record that
drops a gloss or invents one is rejected, never silently fixed (spec §14).

Every record must carry full provenance (spec §8):
  traditional, simplified, pinyin, senses[],
  cc_cedict_version, llm_model, prompt_version, generation_date

The record key must equal the record's own lexical identity, so the mapping
cannot silently disagree with itself (spec §14: fail rather than override).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from ..identity import compute_lexical_identity

# Single normative source (spec §14): the record shape is defined once in
# schemas/llm_entry.json and enforced here — never duplicated in code.
# (schemas/ lives at the repo root, three levels above this module.)
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schemas"
ENTRY_SCHEMA: dict[str, Any] = json.loads(
    (SCHEMAS_DIR / "llm_entry.json").read_text(encoding="utf-8")
)
REQUIRED_FIELDS = tuple(ENTRY_SCHEMA["required"])


class LLMDataError(ValueError):
    """Raised when an LLM dataset file violates the expected structure."""


def record_glosses(record: dict[str, Any]) -> set[str]:
    """Return the set of source glosses covered by a record's senses."""
    return {sense["source_gloss"] for sense in record["senses"]}


def assert_gloss_coverage(record: dict[str, Any], expected_glosses: set[str]) -> None:
    """Accept/reject a record against the CC-CEDICT gloss set for its entry.

    The generated definition must cover every English gloss of the entry —
    no fewer, no others. Raises LLMDataError naming the missing and/or
    extra glosses.
    """
    covered = record_glosses(record)
    expected = set(expected_glosses)
    missing = expected - covered
    extra = covered - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing definition for gloss(es): {sorted(missing)}")
        if extra:
            details.append(f"gloss(es) not in CC-CEDICT: {sorted(extra)}")
        raise LLMDataError(
            f"{record.get('traditional', '?')}|{record.get('simplified', '?')}|"
            f"{record.get('pinyin', '?')}: gloss coverage mismatch — "
            + "; ".join(details)
        )


def validate_record(key: str, record: Any) -> str:
    """Validate one record; return its computed lexical identity.

    Shape is enforced against schemas/llm_entry.json (normative); the
    identity-key match and intra-record gloss uniqueness are relational
    checks JSON Schema cannot express. Raises LLMDataError.
    """
    if not isinstance(record, dict):
        raise LLMDataError(f"{key}: record must be a JSON object")
    try:
        jsonschema.validate(instance=record, schema=ENTRY_SCHEMA)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(p) for p in exc.absolute_path)
        where = f"{key}:{location}" if location else key
        raise LLMDataError(f"{where}: {exc.message}") from None
    seen_glosses: set[str] = set()
    for i, sense in enumerate(record["senses"]):
        if sense["source_gloss"] in seen_glosses:
            raise LLMDataError(
                f"{key}: senses[{i}]: duplicate source_gloss "
                f"{sense['source_gloss']!r} within one record"
            )
        seen_glosses.add(sense["source_gloss"])
    expected_key = compute_lexical_identity(
        record["traditional"], record["simplified"], record["pinyin"]
    )
    if key != expected_key:
        raise LLMDataError(
            f"{key}: record identity mismatch — key implies {key!r} but "
            f"record fields imply {expected_key!r}"
        )
    return expected_key


def load_llm_json(path: str | Path) -> dict[str, dict[str, str]]:
    """Load and fully validate the LLM dataset file.

    Returns the mapping identity -> record. Raises LLMDataError on any
    structural or relationship violation (spec §14).

    Note: gloss-coverage against CC-CEDICT (`assert_gloss_coverage`) is a
    separate step — the loader sees only the JSON file, not CC-CEDICT.
    Phase 9 wires the two together; the check itself lives here so both
    the generation pipeline and validation share one implementation.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LLMDataError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMDataError(f"{path}: top level must be a JSON object")

    validated: dict[str, dict[str, str]] = {}
    for key, record in data.items():
        if not isinstance(key, str) or not key.strip():
            raise LLMDataError(f"{path}: identity keys must be non-empty strings")
        validate_record(key, record)
        validated[key] = record
    return validated
