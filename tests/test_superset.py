"""Tests for the pair-level newest-wins superset builder."""

import pytest

from cxdict.parser.u8 import DictionaryEntry
from cxdict.superset import attribute_contribution, build_superset, load_layers


def entry(trad, simp, pin, defs=("d",)):
    return DictionaryEntry(
        traditional=trad, simplified=simp, pinyin=pin, definitions=tuple(defs)
    )


def ids(superset):
    return [e.lexical_id() for e in superset.entries]


def test_newest_layer_kept_wholesale_plus_retired_pairs_in_order():
    old = [
        entry("N", "N", "N G", ("blooper",)),
        entry("R", "R", "P1", ("gone",)),
    ]
    new = [
        entry("N", "N", "NG", ("outtake",)),
        entry("W", "W", "P9", ("shiny",)),
    ]
    result = build_superset([("2026-09-12", new), ("2025-08-08", old)])
    # Newest file order first, then retired pairs in older-layer file order.
    assert ids(result) == ["N|N|NG", "W|W|P9", "R|R|P1"]
    assert result.holder == {
        "N|N|NG": "2026-09-12",
        "W|W|P9": "2026-09-12",
        "R|R|P1": "2025-08-08",
    }


def test_rekey_keeps_new_row_only():
    old = [entry("A", "A", "bu4 X", ("same",))]
    new = [entry("A", "A", "Bu4 X", ("same",))]
    result = build_superset([("new", new), ("old", old)])
    assert ids(result) == ["A|A|Bu4 X"]


def test_gloss_rewrite_keeps_new_row_only():
    old = [entry("K", "K", "P1", ("ancient",))]
    new = [entry("K", "K", "P1", ("modern",))]
    result = build_superset([("new", new), ("old", old)])
    assert ids(result) == ["K|K|P1"]
    assert result.entries[0].definitions == ("modern",)


def test_polyphone_dropped_reading_stays_dropped():
    old = [entry("L", "L", "le4", ("happy",)), entry("L", "L", "yue4", ("music",))]
    new = [entry("L", "L", "le4", ("happy",))]
    result = build_superset([("new", new), ("old", old)])
    assert ids(result) == ["L|L|le4"]


def test_polyphone_shared_readings_all_kept_from_newest_layer():
    old = [entry("L", "L", "le4", ("happy",))]
    new = [
        entry("L", "L", "le4", ("happy",)),
        entry("L", "L", "yue4", ("music",)),
    ]
    result = build_superset([("new", new), ("old", old)])
    assert ids(result) == ["L|L|le4", "L|L|yue4"]


def test_contribution_counts_sum_to_totals():
    old = [entry("N", "N", "P0", ("x",)), entry("R", "R", "P1", ("gone",))]
    new = [entry("N", "N", "P0", ("x",)), entry("W", "W", "P9", ("shiny",))]
    result = build_superset([("2026-09-12", new), ("2025-08-08", old)])
    contrib = attribute_contribution(result)
    assert contrib == {
        "2026-09-12": {"rows": 2, "pairs": 2},
        "2025-08-08": {"rows": 1, "pairs": 1},
    }
    assert sum(v["rows"] for v in contrib.values()) == len(result.entries)
    assert sum(v["pairs"] for v in contrib.values()) == len(result.pair_holder)


def test_empty_layers_yield_empty_superset():
    result = build_superset([])
    assert result.entries == [] and result.holder == {}


def test_load_layers_parses_manifest_newest_first(tmp_path):
    cc = tmp_path / "cc-cedict"
    cc.mkdir()
    (cc / "2026-09-12.u8").write_text(
        "N N [NG] /outtake/\n", encoding="utf-8"
    )
    (cc / "2025-08-08.u8").write_text(
        "R R [P1] /gone/\n", encoding="utf-8"
    )
    (cc / "snapshots.toml").write_text(
        "[[snapshot]]\n"
        'date = "2026-09-12"\nfile = "2026-09-12.u8"\n'
        'upstream_date = "2026-09-12T07:35:13Z"\nupstream_time = 1\n'
        'upstream_sha256 = ""\ncontent_sha256 = "x"\nentries = 1\npairs = 1\n'
        "[[snapshot]]\n"
        'date = "2025-08-08"\nfile = "2025-08-08.u8"\n'
        'upstream_date = "2025-08-08T05:26:26Z"\nupstream_time = 0\n'
        'upstream_sha256 = ""\ncontent_sha256 = "y"\nentries = 1\npairs = 1\n',
        encoding="utf-8",
    )
    layers = load_layers(cc)
    assert [date for date, _ in layers] == ["2026-09-12", "2025-08-08"]
    assert ids(build_superset(layers)) == ["N|N|NG", "R|R|P1"]


def test_load_layers_fails_on_malformed_rows(tmp_path):
    cc = tmp_path / "cc-cedict"
    cc.mkdir()
    (cc / "2026-09-12.u8").write_text("this is not an entry\n", encoding="utf-8")
    (cc / "snapshots.toml").write_text(
        "[[snapshot]]\n"
        'date = "2026-09-12"\nfile = "2026-09-12.u8"\n'
        'upstream_date = "2026-09-12T07:35:13Z"\nupstream_time = 1\n'
        'upstream_sha256 = ""\ncontent_sha256 = "x"\nentries = 0\npairs = 0\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_layers(cc)
