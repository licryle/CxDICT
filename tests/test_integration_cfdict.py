"""Integration test: parse the authoritative CFDICT source (spec §2, §14).

Skipped when cfdict.u8 has not been forked into the repository yet.
"""

from pathlib import Path

import pytest

from cxdict.parser.u8 import parse_u8_file

CFDICT = (
    Path(__file__).resolve().parent.parent
    / "dictionaries" / "fr" / "data" / "cfdict.u8"
)

pytestmark = pytest.mark.skipif(
    not CFDICT.exists(), reason="cfdict.u8 not forked into dictionaries/fr/ yet"
)


def test_full_cfdict_parses_cleanly():
    entries, errors = parse_u8_file(CFDICT)
    assert errors == [], f"malformed lines: {errors[:5]}"
    # Snapshot known to contain ~56k entries; guard against regressions.
    assert len(entries) >= 50_000
    # CFDICT contains duplicate entries which are now merged by lexical identity.
    # The lexical_id uniqueness check is done at assembly time.


def test_cfdict_definitions_are_french():
    entries, _ = parse_u8_file(CFDICT)
    by_id = {e.lexical_id(): e for e in entries}
    china = by_id["中國|中国|Zhong1 guo2"]
    assert any("Chine" in d or "chine" in d for d in china.definitions)
