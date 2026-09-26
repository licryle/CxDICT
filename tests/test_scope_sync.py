"""Tests for rule-3 pruning (src/cxdict/scope_sync.py + cli)."""

import json
import shutil

import pytest

from cxdict.parser.u8 import DictionaryEntry
from cxdict.scope_sync import (
    compare_pair_scopes,
    find_human_warnings,
    find_invalid_llm,
    sync_language_files,
)

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


def entry(trad, simp, pin, defs=("d",)):
    return DictionaryEntry(
        traditional=trad, simplified=simp, pinyin=pin, definitions=tuple(defs)
    )


def record(trad, simp, pin, glosses=("d",)):
    return {
        "traditional": trad, "simplified": simp, "pinyin": pin,
        "senses": [{"source_gloss": g, "definition": "x"} for g in glosses],
        "cc_cedict_version": "v", "llm_model": "m",
        "prompt_version": "p", "generation_date": "2026-01-01T00:00:00+00:00",
    }


SUPERSET = [
    entry("K", "K", "P1", ("a", "b")),
    entry("N", "N", "NG", ("outtake",)),
    entry("L", "L", "le4", ("happy",)),
]


def test_compare_pair_scopes_counts():
    old = [entry("K", "K", "P1", ("a",)), entry("G", "G", "P2", ("b",))]
    new = [entry("K", "K", "P1", ("a-changed",)), entry("N", "N", "P3", ("c",))]
    assert compare_pair_scopes(old, new) == {
        "new_pairs": 1, "retired_pairs": 1, "changed_pairs": 1, "identical_pairs": 0,
    }
    assert compare_pair_scopes(old, old) == {
        "new_pairs": 0, "retired_pairs": 0, "changed_pairs": 0, "identical_pairs": 2,
    }
    # Pinyin-only change still counts as changed (row sets differ).
    assert compare_pair_scopes(
        [entry("K", "K", "P1", ("a",))], [entry("K", "K", "P2", ("a",))]
    )["changed_pairs"] == 1


def test_find_invalid_llm_categories_in_key_order():
    llm = {
        "K|K|P1": record("K", "K", "P1", ("a", "b")),  # valid
        "K|K|P9": record("K", "K", "P9", ("a",)),  # pinyin not in readings
        "N|N|N G": record("N", "N", "N G", ("outtake",)),  # re-keyed upstream
        "N|N|NG": record("N", "N", "NG", ("stale",)),  # gloss changed
        "Z|Z|P7": record("Z", "Z", "P7", ("gone",)),  # pair in no snapshot
    }
    invalid = find_invalid_llm(SUPERSET, llm)
    assert [(r.key, r.category) for r in invalid] == [
        ("K|K|P9", "pinyin_invalid"),
        ("N|N|N G", "pinyin_invalid"),
        ("N|N|NG", "gloss_mismatch"),
        ("Z|Z|P7", "pair_missing"),
    ]


def test_find_human_warnings_never_checks_glosses():
    human = [
        entry("K", "K", "P1", ("whatever free-form",)),  # valid despite glosses
        entry("K", "K", "P9", ("x",)),
        entry("Z", "Z", "P7", ("y",)),
    ]
    warnings = find_human_warnings(SUPERSET, human)
    assert [(w.key, w.category) for w in warnings] == [
        ("K|K|P9", "pinyin_invalid"),
        ("Z|Z|P7", "pair_missing"),
    ]


def write_lang(tmp_path, llm, human_text=""):
    human = tmp_path / "human.u8"
    human.write_text(human_text, encoding="utf-8")
    data = tmp_path / "llm.json"
    data.write_text(json.dumps(llm, ensure_ascii=False), encoding="utf-8")
    return human, data


def test_records_matching_retired_rows_stay_valid(tmp_path):
    """The anti-churn guarantee: content kept via older layers is stable.

    A record generated from a retired pair's older-layer row matches the
    superset canonical row, so repeated prune runs never flag it — no
    prune-then-regenerate cycle across pipeline runs (including restarts).
    """
    from cxdict.superset import build_superset

    newest = [entry("N", "N", "NG", ("outtake",))]
    older = [
        entry("N", "N", "NG", ("outtake",)),
        entry("R", "R", "P1", ("gone",)),  # retired pair, older layer only
    ]
    superset = build_superset([("new", newest), ("old", older)])
    llm = {
        "N|N|NG": record("N", "N", "NG", ("outtake",)),
        "R|R|P1": record("R", "R", "P1", ("gone",)),
    }
    assert find_invalid_llm(superset.entries, llm) == []
    human, data = write_lang(tmp_path, llm)
    first = sync_language_files(superset.entries, human, data, code="t",
                                apply=True, force=True)
    assert not first.invalid and not first.pruned
    second = sync_language_files(superset.entries, human, data, code="t",
                                 apply=True, force=True)
    assert not second.invalid and not second.pruned
    assert data.read_text(encoding="utf-8") == json.dumps(
        llm, ensure_ascii=False)


def test_dry_run_reports_without_writing(tmp_path):
    llm = {"K|K|P1": record("K", "K", "P1", ("a", "b")),
           "Z|Z|P7": record("Z", "Z", "P7", ("gone",))}
    human, data = write_lang(tmp_path, llm)
    before = data.read_text(encoding="utf-8")
    report = sync_language_files(SUPERSET, human, data, code="t")
    assert report.llm_total == 2
    assert [r.key for r in report.invalid] == ["Z|Z|P7"]
    assert not report.pruned and not report.refused
    assert data.read_text(encoding="utf-8") == before


def test_apply_prunes_and_keeps_valid(tmp_path):
    llm = {"K|K|P1": record("K", "K", "P1", ("a", "b")),
           "Z|Z|P7": record("Z", "Z", "P7", ("gone",))}
    human, data = write_lang(tmp_path, llm)
    report = sync_language_files(SUPERSET, human, data, code="t", apply=True,
                                 force=True)
    assert report.pruned
    assert list(json.loads(data.read_text(encoding="utf-8"))) == ["K|K|P1"]


def test_apply_refuses_above_threshold_without_force(tmp_path):
    llm = {f"K{i}|K{i}|P{i}": record(f"K{i}", f"K{i}", f"P{i}", ("gone",))
           for i in range(10)}
    llm["K|K|P1"] = record("K", "K", "P1", ("a", "b"))
    human, data = write_lang(tmp_path, llm)
    report = sync_language_files(SUPERSET, human, data, code="t", apply=True)
    assert report.refused and not report.pruned
    assert len(json.loads(data.read_text(encoding="utf-8"))) == 11
    forced = sync_language_files(SUPERSET, human, data, code="t", apply=True,
                                 force=True)
    assert forced.pruned
    assert list(json.loads(data.read_text(encoding="utf-8"))) == ["K|K|P1"]


def _write_tree(root):
    """Minimal tree: fr language skeleton + one logged snapshot."""
    src_lang = REPO / "dictionaries" / "fr"
    dst_lang = root / "dictionaries" / "fr"
    shutil.copytree(src_lang / "assets", dst_lang / "assets")
    shutil.copy(src_lang / "dict.toml", dst_lang / "dict.toml")
    (root / "dictionaries" / "fr" / "data").mkdir(parents=True)
    (root / "dictionaries" / "fr" / "data" / "cfdict.u8").write_text("", encoding="utf-8")
    (root / "dictionaries" / "fr" / "data" / "human.u8").write_text("", encoding="utf-8")
    llm = {"K|K|P1": record("K", "K", "P1", ("a", "b")),
           "Z|Z|P7": record("Z", "Z", "P7", ("gone",))}
    (root / "dictionaries" / "fr" / "data" / "llm_generated.json").write_text(
        json.dumps(llm, ensure_ascii=False), encoding="utf-8")
    cc = root / "dictionaries" / "cc-cedict"
    cc.mkdir(parents=True)
    (cc / "2026-09-12.u8").write_text(
        "K K [P1] /a/b/\nN N [NG] /outtake/\nL L [le4] /happy/\n",
        encoding="utf-8")
    (cc / "snapshots.toml").write_text(
        "[[snapshot]]\n"
        'date = "2026-09-12"\nfile = "2026-09-12.u8"\n'
        'upstream_date = "2026-09-12T07:35:13Z"\nupstream_time = 1\n'
        'upstream_sha256 = ""\ncontent_sha256 = "x"\nentries = 3\npairs = 3\n',
        encoding="utf-8")


def test_cli_dry_run_default_and_apply(tmp_path, monkeypatch, capsys):
    from cxdict.cli.scope_sync import main

    _write_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "[fr] llm records: 2, invalid: 1" in out
    assert "pair_missing: 1" in out
    assert "dry run" in out
    data = tmp_path / "dictionaries" / "fr" / "data" / "llm_generated.json"
    assert len(json.loads(data.read_text(encoding="utf-8"))) == 2
    assert main(["--apply", "--force"]) == 0
    assert list(json.loads(data.read_text(encoding="utf-8"))) == ["K|K|P1"]
