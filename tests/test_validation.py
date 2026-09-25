"""Tests for validation tooling (Phase 9, spec §14).

Each spec relationship gets a passing case and at least one failing case.
"""

import json
from pathlib import Path

import pytest

from cfdict_next.assembly import assemble, write_u8_file
from cfdict_next.scope_info import ReleaseSources, build_scope_info
from cfdict_next.validation import (
    ValidationReport,
    check_no_overlap,
    check_outputs,
    check_scope_info,
    validate_inputs,
)

REPO = Path(__file__).resolve().parent.parent

BASE_SAMPLE = (
    "# sample\n"
    "中國 中国 [Zhong1 guo2] /Chine/\n"
    "行 行 [Xing2] /marcher/\n"
)
CC_SAMPLE = (
    "# sample\n"
    "中國 中国 [Zhong1 guo2] /China/Middle Kingdom/\n"
    "行 行 [Xing2] /to walk/\n"
    "美 美 [Mei3] /beautiful/\n"
)

CHINA = "中國|中国|Zhong1 guo2"
WALK = "行|行|Xing2"
BEAUTY = "美|美|Mei3"


def record_for(key, glosses):
    trad, simp, pin = key.split("|")
    return {
        "traditional": trad,
        "simplified": simp,
        "pinyin": pin,
        "senses": [{"source_gloss": g, "definition": f"fr-{g}"} for g in glosses],
        "cc_cedict_version": "v",
        "llm_model": "m",
        "prompt_version": "p",
        "generation_date": "2025-01-01T00:00:00+00:00",
    }


def write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def fixture_files(tmp_path, cc=CC_SAMPLE, base=BASE_SAMPLE,
                  human="", llm_generated=None):
    base_p = write(tmp_path / "cfdict.u8", base)
    cc_p = write(tmp_path / "cc.u8", cc)
    human_p = write(tmp_path / "human.u8", human)
    llm_p = write(
        tmp_path / "llm_generated.json",
        json.dumps(llm_generated if llm_generated is not None else {}, ensure_ascii=False),
    )
    return base_p, cc_p, human_p, llm_p


def test_happy_path_passes(tmp_path):
    llm_generated = {BEAUTY: record_for(BEAUTY, ["beautiful"])}
    paths = fixture_files(tmp_path, llm_generated=llm_generated)
    report, data = validate_inputs(*paths)
    assert report.passed, [ (c.name, c.detail) for c in report.failures() ]
    assert data is not None
    assert set(data["llm_generated"]) == {BEAUTY}


def test_malformed_base_fails(tmp_path):
    paths = fixture_files(tmp_path, base="not an entry\n")
    report, data = validate_inputs(*paths)
    assert not report.passed
    assert data is None
    assert any(c.name == "base parses" and not c.passed for c in report.checks)


def test_malformed_human_fails(tmp_path):
    paths = fixture_files(tmp_path, human="not an entry\n")
    report, data = validate_inputs(*paths)
    assert not report.passed
    assert data is None
    assert any(c.name == "human.u8 parses" and not c.passed for c in report.checks)


def test_invalid_llm_json_fails(tmp_path):
    base_p, cc_p, human_p, _ = fixture_files(tmp_path)
    llm_p = write(tmp_path / "llm_generated.json", "{bad")
    report, data = validate_inputs(base_p, cc_p, human_p, llm_p)
    assert not report.passed and data is None


def test_each_overlap_pair_fails():
    for human_ids, llm_generated, base_ids, name in (
        ({CHINA}, {}, {CHINA}, "base/human"),
        ({}, {CHINA: {}}, {CHINA}, "base/LLM"),
        ({BEAUTY}, {BEAUTY: {}}, set(), "human/LLM"),
    ):
        report = ValidationReport()
        check_no_overlap(base_ids, human_ids, llm_generated, report)
        assert not report.passed, name
        assert any(c.name == f"no {name} overlap" and not c.passed for c in report.checks)


def test_gloss_mismatch_fails(tmp_path):
    # BEAUTY record drops nothing but the gloss text differs from CC-CEDICT.
    llm_generated = {BEAUTY: record_for(BEAUTY, ["pretty"])}
    paths = fixture_files(tmp_path, llm_generated=llm_generated)
    report, _ = validate_inputs(*paths)
    assert not report.passed
    assert any(c.name == "LLM gloss coverage" and not c.passed for c in report.checks)


def test_llm_outside_cc_cedict_fails(tmp_path):
    llm_generated = {"好|好|Hao3": record_for("好|好|Hao3", ["good"])}
    paths = fixture_files(tmp_path, llm_generated=llm_generated)
    report, _ = validate_inputs(*paths)
    assert not report.passed
    assert any("outside CC-CEDICT scope" in c.detail for c in report.failures())


def test_human_hanzi_mismatch_fails(tmp_path):
    # CC knows 中國/中国; human mixes 中國 with wrong simplified 美.
    paths = fixture_files(tmp_path, human="中國 美 [Zhong1 guo2] /Chine/\n")
    report, _ = validate_inputs(*paths)
    assert not report.passed
    assert any(c.name == "human hanzi/pinyin" and not c.passed for c in report.checks)


def test_human_pinyin_mismatch_fails(tmp_path):
    # Correct hanzi pair but wrong pinyin for the known CC-CEDICT entry.
    paths = fixture_files(tmp_path, human="中國 中国 [Zhong9 guo9] /Chine/\n")
    report, _ = validate_inputs(*paths)
    assert not report.passed
    assert any(c.name == "human hanzi/pinyin" and not c.passed for c in report.checks)


def test_human_novel_entry_passes(tmp_path):
    # Fully novel hanzi pair outside CC-CEDICT scope is allowed (free-form).
    paths = fixture_files(tmp_path, human="𠀀 𠀁 [Xx1] /truc/\n")
    report, _ = validate_inputs(*paths)
    assert report.passed, [(c.name, c.detail) for c in report.failures()]


def test_human_valid_cc_entry_passes(tmp_path):
    paths = fixture_files(tmp_path, human="美 美 [Mei3] /beau/\n")
    report, _ = validate_inputs(*paths)
    assert report.passed, [(c.name, c.detail) for c in report.failures()]


def test_scope_info_consistency():
    sources = ReleaseSources(
        cc_cedict_version="v", cc_cedict_ids={"A", "B"},
        base_version="v", base_ids={"A"},
        human_version="v", human_ids=set(),
        llm_generated_version="v", llm_generated_ids=set(),
    )
    info = build_scope_info(sources, generated_at="T")
    report = ValidationReport()
    check_scope_info(info, sources, report)
    assert report.passed
    tampered = {**info, "coverage": {**info["coverage"], "missing_scope_total": 99}}
    report2 = ValidationReport()
    check_scope_info(tampered, sources, report2)
    assert not report2.passed


def test_outputs_content_checked(tmp_path):
    base_p, cc_p, human_p, llm_p = fixture_files(tmp_path)
    report, data = validate_inputs(base_p, cc_p, human_p, llm_p)
    assert report.passed
    # Assemble empty-human/LLM outputs and validate them end to end.
    from cfdict_next.parser.u8 import parse_u8_file

    entries, _ = parse_u8_file(base_p)
    human_entries, full_entries = assemble(entries, [], {})
    out_c, out_f = tmp_path / "c.u8", tmp_path / "f.u8"
    write_u8_file(out_c, human_entries)
    write_u8_file(out_f, full_entries)
    out_report = ValidationReport()
    check_outputs(out_c, out_f, data["base_ids"], set(), set(), out_report)
    assert out_report.passed


def test_output_missing_entry_fails(tmp_path):
    out_c = write(tmp_path / "c.u8", "中國 中国 [Zhong1 guo2] /Chine/\n")
    out_f = write(tmp_path / "f.u8", "中國 中国 [Zhong1 guo2] /Chine/\n")
    report = ValidationReport()
    check_outputs(out_c, out_f, {CHINA, WALK}, set(), set(), report)
    assert not report.passed
    assert any(c.name == "human output content" and not c.passed for c in report.checks)


def test_output_duplicates_fail(tmp_path):
    line = "中國 中国 [Zhong1 guo2] /Chine/\n"
    out_c = write(tmp_path / "c.u8", line + line)
    out_f = write(tmp_path / "f.u8", line)
    report = ValidationReport()
    check_outputs(out_c, out_f, {CHINA}, set(), set(), report)
    assert not report.passed
    assert any("duplicates" in c.name and not c.passed for c in report.checks)


def test_cli_exit_codes(tmp_path, capsys):
    from cfdict_next.cli.validate import main as cli_main

    paths = fixture_files(
        tmp_path, llm_generated={BEAUTY: record_for(BEAUTY, ["beautiful"])}
    )
    rc = cli_main(
        ["--language", "fr", "--base", str(paths[0]), "--cc-cedict", str(paths[1]),
         "--human", str(paths[2]), "--llm-generated", str(paths[3])]
    )
    assert rc == 0
    assert "validation passed" in capsys.readouterr().out
    bad = fixture_files(tmp_path, base="junk\n")
    rc = cli_main(
        ["--language", "fr", "--base", str(bad[0]), "--cc-cedict", str(bad[1]),
         "--human", str(bad[2]), "--llm-generated", str(bad[3])]
    )
    assert rc == 1


def test_cli_requires_language(tmp_path):
    from cfdict_next.cli.validate import main as cli_main

    paths = fixture_files(tmp_path)
    with pytest.raises(SystemExit):
        cli_main(["--base", str(paths[0])])
    with pytest.raises(SystemExit):
        cli_main(["--language", "xx-unknown", "--base", str(paths[0])])


def test_none_base_passes_with_empty_identities(tmp_path):
    _, cc_p, human_p, llm_p = fixture_files(tmp_path)
    report, data = validate_inputs(None, cc_p, human_p, llm_p)
    assert report.passed, [(c.name, c.detail) for c in report.failures()]
    assert data is not None and data["base_ids"] == set()
