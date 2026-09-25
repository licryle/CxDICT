"""Tests for the cleanup script (Phase 6, spec §9, §14).

Covers each precedence rule in isolation and together, dry-run behavior,
and fail-loud handling of malformed inputs.
"""

import json

import pytest

from cfdict_next.cleanup import (
    base_identities,
    cleanup_datasets,
    cleanup_files,
    human_identities,
)


def write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def record_for(key):
    """Build a valid record whose fields match its identity key."""
    trad, simp, pin = key.split("|")
    return {
        "traditional": trad,
        "simplified": simp,
        "pinyin": pin,
        "senses": [{"source_gloss": "g", "definition": "d"}],
        "cc_cedict_version": "v",
        "llm_model": "m",
        "prompt_version": "p",
        "generation_date": "2025-01-01T00:00:00+00:00",
    }


BASE_SAMPLE = (
    "# sample\n"
    "中國 中国 [Zhong1 guo2] /Chine/\n"
    "行 行 [Xing2] /marcher/\n"
)

CHINA = "中國|中国|Zhong1 guo2"
WALK = "行|行|Xing2"
OTHER = "美|美|Mei3"
FOURTH = "好|好|Hao3"


def test_human_entries_in_base_are_removed():
    kept_human, kept_llm, report = cleanup_datasets({CHINA}, {CHINA, OTHER}, {})
    assert kept_human == {OTHER}
    assert kept_llm == {}
    assert report.human_removed_base == 1
    assert report.human_after == 1


def test_llm_entries_in_base_are_removed():
    llm = {CHINA: record_for(CHINA), OTHER: record_for(OTHER)}
    _, kept, report = cleanup_datasets({CHINA}, set(), llm)
    assert set(kept) == {OTHER}
    assert report.llm_removed_base == 1


def test_llm_entries_in_human_are_removed():
    # Same identity in both: human wins, LLM copy goes.
    llm = {WALK: record_for(WALK), OTHER: record_for(OTHER)}
    kept_h, kept_l, report = cleanup_datasets(set(), {WALK}, llm)
    assert kept_h == {WALK}
    assert set(kept_l) == {OTHER}
    assert report.llm_removed_human == 1


def test_base_beats_human_for_llm_too():
    # Entry in all three datasets: survives only implicitly via base.
    llm = {CHINA: record_for(CHINA)}
    kept_h, kept_l, report = cleanup_datasets({CHINA}, {CHINA}, llm)
    assert kept_h == set()
    assert kept_l == {}
    assert report.llm_removed_base == 1
    assert report.llm_removed_human == 0  # counted under base


def test_no_overlap_is_a_no_op():
    llm = {OTHER: record_for(OTHER)}
    kept_h, kept_l, report = cleanup_datasets({CHINA}, {WALK}, llm)
    assert kept_h == {WALK} and kept_l == llm
    assert report.human_after == 1 and report.llm_after == 1


def test_cleanup_files_end_to_end(tmp_path):
    base = write(tmp_path / "cfdict.u8", BASE_SAMPLE)
    human_p = write(
        tmp_path / "human.u8",
        "行 行 [Xing2] /marcher/\n美 美 [Mei3] /beau/\n",
    )
    llm_p = write(
        tmp_path / "llm_generated.json",
        json.dumps(
            {
                CHINA: record_for(CHINA),
                OTHER: record_for(OTHER),
                FOURTH: record_for(FOURTH),
            },
            ensure_ascii=False,
        ),
    )
    report = cleanup_files(base, human_p, llm_p)
    # WALK dropped from human (now in base); CHINA dropped from LLM
    # (now in base); OTHER dropped from LLM (kept human);
    # FOURTH survives in LLM (nowhere else).
    assert report.human_after == 1
    assert report.llm_after == 1
    from cfdict_next.parser.u8 import parse_u8_file

    human_entries, _ = parse_u8_file(human_p)
    assert {e.lexical_id() for e in human_entries} == {OTHER}
    assert set(json.loads(llm_p.read_text(encoding="utf-8"))) == {FOURTH}


def test_dry_run_writes_nothing(tmp_path):
    base = write(tmp_path / "cfdict.u8", BASE_SAMPLE)
    human_p = write(tmp_path / "human.u8", "中國 中国 [Zhong1 guo2] /Chine/\n")
    llm_p = write(tmp_path / "llm_generated.json", json.dumps({}))
    before_h, before_l = (
        human_p.read_bytes(),
        llm_p.read_bytes(),
    )
    report = cleanup_files(base, human_p, llm_p, dry_run=True)
    assert report.human_removed_base == 1
    assert human_p.read_bytes() == before_h
    assert llm_p.read_bytes() == before_l


def test_malformed_base_fails_loudly(tmp_path):
    base = write(tmp_path / "cfdict.u8", "this is not an entry\n")
    with pytest.raises(ValueError, match="malformed"):
        base_identities(base)


def test_malformed_human_fails_loudly(tmp_path):
    human = write(tmp_path / "human.u8", "this is not an entry\n")
    with pytest.raises(ValueError, match="malformed"):
        human_identities(human)


def test_invalid_llm_json_fails_loudly(tmp_path):
    base = write(tmp_path / "cfdict.u8", BASE_SAMPLE)
    human_p = write(tmp_path / "human.u8", "")
    llm_p = write(tmp_path / "llm_generated.json", "{bad json")
    with pytest.raises(Exception, match="[Ii]nvalid JSON"):
        cleanup_files(base, human_p, llm_p)


def test_no_base_means_empty_identity_set():
    assert base_identities(None) == set()


def test_cli_requires_language(tmp_path):
    from cfdict_next.cli.cleanup import main as cli_main

    base = write(tmp_path / "cfdict.u8", BASE_SAMPLE)
    with pytest.raises(SystemExit):
        cli_main(["--base", str(base)])
    with pytest.raises(SystemExit):
        cli_main(["--language", "xx-unknown", "--base", str(base)])
