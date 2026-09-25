"""Integration test: parse the real CC-CEDICT snapshot in data/ (spec §3, §14).

Skipped when the snapshot has not been downloaded yet.
"""

from pathlib import Path

import pytest

from cxdict.parser.u8 import parse_u8_file

CEDICT_GZ = Path(__file__).resolve().parent.parent / "data" / "cc-cedict" / "cedict_1_0_ts_utf-8_mdbg.txt.gz"

pytestmark = pytest.mark.skipif(
    not CEDICT_GZ.exists(), reason="CC-CEDICT snapshot not downloaded"
)


def test_full_cc_cedict_snapshot_parses_cleanly():
    entries, errors = parse_u8_file(CEDICT_GZ)
    assert errors == [], f"malformed lines: {errors[:5]}"
    # Snapshot known to contain ~125k entries; guard against regressions.
    assert len(entries) >= 120_000
    # Identity must be unique per (traditional, simplified, pinyin) in CEDICT.
    ids = {e.lexical_id() for e in entries}
    assert len(ids) == len(entries), "duplicate lexical identities in CC-CEDICT"
