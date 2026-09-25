"""Tests for release scope information (Phase 8, spec §12, §16)."""

import json

import pytest

from cfdict_next.scope_info import (
    ReleaseSources,
    build_scope_info,
    collect_llm_provenance,
    render_scope_markdown,
    sha256_file,
)


def sources(**overrides):
    args = {
        "cc_cedict_version": "cc-v1",
        "cc_cedict_ids": {"A", "B", "C", "D"},
        "base_version": "base-v1",
        "base_ids": {"A"},
        "human_version": "human-v1",
        "human_ids": {"B"},
        "llm_generated_version": "llm-v1",
        "llm_generated_ids": {"C"},
        "llm_models": ("m1",),
        "prompt_versions": ("p1",),
    }
    args.update(overrides)
    return ReleaseSources(**args)


def test_scope_info_matches_exact_inputs():
    info = build_scope_info(sources(), generated_at="2025-01-01T00:00:00+00:00")
    assert info["generated_at"] == "2025-01-01T00:00:00+00:00"
    assert info["sources"]["cc_cedict"] == {"version": "cc-v1", "entries": 4}
    assert info["sources"]["base"] == {"version": "base-v1", "entries": 1}
    assert info["sources"]["human"] == {"version": "human-v1", "entries": 1}
    assert info["sources"]["llm_generated"] == {"version": "llm-v1", "entries": 1}
    assert info["provenance"] == {"llm_models": ["m1"], "prompt_versions": ["p1"]}
    assert info["coverage"]["missing_scope_total"] == 1  # D only
    assert info["coverage"]["human_dictionary_total"] == 2
    assert info["coverage"]["full_dictionary_total"] == 3


def test_markdown_contains_figures_and_versions():
    markdown = render_scope_markdown(
        build_scope_info(sources(), generated_at="T"), "CFDICT"
    )
    for needle in (
        "cc-v1", "base-v1", "human-v1", "llm-v1",
        "| CFDICT (authoritative) |",
        "CFDICT covers 1 CC-CEDICT entries",
        "Human dictionary: 2 entries",
        "Full dictionary: 3 entries",
        "Missing scope (still to generate): 1",
        "LLM models: m1",
        "Prompt versions: p1",
    ):
        assert needle in markdown, needle


def test_markdown_uses_base_label():
    markdown = render_scope_markdown(
        build_scope_info(sources(), generated_at="T"), "Base"
    )
    assert "| Base (authoritative) |" in markdown
    assert "Base covers 1 CC-CEDICT entries" in markdown


def test_empty_llm_data_renders_na_provenance():
    info = build_scope_info(
        sources(
            human_ids={"B"}, llm_generated_ids=set(),
            llm_models=(), prompt_versions=(),
        )
    )
    assert info["coverage"]["human_dictionary_total"] == 2
    assert info["coverage"]["full_dictionary_total"] == 2
    markdown = render_scope_markdown(info, "CFDICT")
    assert "LLM models: n/a" in markdown
    assert "Prompt versions: n/a" in markdown


def test_collect_llm_provenance_dedupes_and_sorts():
    records = {
        "K1": {"llm_model": "b", "prompt_version": "p2"},
        "K2": {"llm_model": "a", "prompt_version": "p2"},
        "K3": {"llm_model": "a", "prompt_version": "p1"},
    }
    models, prompts = collect_llm_provenance(records)
    assert models == ("a", "b")
    assert prompts == ("p1", "p2")


def test_sha256_file_pins_exact_bytes(tmp_path):
    f = tmp_path / "x.u8"
    f.write_bytes("中國 中国 [Zhong1 guo2] /Chine/\n".encode("utf-8"))
    digest = sha256_file(f)
    assert digest.startswith("sha256:")
    (tmp_path / "y.u8").write_bytes(b"changed\n")
    assert sha256_file(tmp_path / "y.u8") != digest


def test_cli_on_real_data(tmp_path):
    from cfdict_next.cli.scope_info import main as cli_main

    (tmp_path / "llm.json").write_text("{}", encoding="utf-8")
    (tmp_path / "human.u8").write_text("", encoding="utf-8")
    out = tmp_path / "scope.md"
    rc = cli_main(
        [
            "--language", "fr",
            "--base", "data/fr/cfdict.u8",
            "--human", str(tmp_path / "human.u8"),
            "--llm-generated", str(tmp_path / "llm.json"),
            "--cc-cedict", "data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
            "--out", str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "sha256:" in text  # default content-hash versions
    assert "56300" in text or "56,300" in text or "56279" in text
    assert "| CFDICT (authoritative) |" in text


def test_cli_requires_language(tmp_path):
    import pytest

    from cfdict_next.cli.scope_info import main as cli_main

    with pytest.raises(SystemExit):
        cli_main(["--base", "data/cfdict.u8"])
    assert cli_main(["--language", "xx-unknown", "--base", "data/cfdict.u8"]) == 1
