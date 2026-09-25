"""Unit tests for the TOML-driven language registry (src/cxdict/languages.py).

Language definitions live outside the package in assets/<code>/dict.toml;
these tests pin the loader behavior and path resolution.
"""

from pathlib import Path

import pytest

from cxdict.languages import get_language, resolve_paths

REPO = Path(__file__).resolve().parent.parent


def test_french_config_matches_current_pipeline_reality():
    fr = get_language("fr")
    assert fr.code == "fr"
    assert fr.base_filename == "cfdict.u8"
    assert fr.base_label == "CFDICT"
    assert fr.base_url == "https://chine.in/mandarin/dictionnaire/CFDICT/"
    assert fr.prompt_template.name == "generate_fr_v6.txt"
    assert fr.prompt_template.is_file()
    assert fr.few_shot.name == "few_shot_examples.json"
    assert fr.few_shot.is_file()
    assert fr.prompt_version == "v6"
    assert fr.prompt_user_intro == (
        "Translate the meanings of the Chinese entries below into French.\n"
        "Entries to translate:\n"
    )
    assert fr.target_language_name == "French"
    assert fr.output_slug == "cfdict"
    assert fr.config_dir == REPO / "assets" / "fr"


def test_hsk3_config_has_no_base():
    hsk = get_language("zh-CN-HSK03")
    assert hsk.base_filename is None
    assert hsk.base_url is None
    assert hsk.prompt_version == "v1"
    assert hsk.prompt_template.name == "generate_hsk3_v1.txt"
    assert hsk.prompt_user_intro.startswith("Explain the meanings")
    assert "HSK3" in hsk.description
    assert "HSK3" in hsk.target_language_name


def test_unknown_language_fails_loudly():
    with pytest.raises(ValueError, match="xx-unknown"):
        get_language("xx-unknown")


def test_path_traversal_codes_are_rejected():
    for bad in ("../fr", "..\\fr", "..", "", "fr/extra"):
        with pytest.raises(ValueError, match="invalid|unknown"):
            get_language(bad)


def _write_minimal_toml(directory, code):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "template.txt").write_text("T {example_lines}\n", encoding="utf-8")
    (directory / "shots.json").write_text(
        '[{"simplified": "x", "traditional": "x", "pinyin": "Xx1", '
        '"english": "g", "definition": "d"}]',
        encoding="utf-8",
    )
    (directory / "dict.toml").write_text(
        f"code = {code!r}\n"
        'base_label = "B"\n'
        'prompt_template = "template.txt"\n'
        'few_shot = "shots.json"\n'
        'prompt_version = "v0"\n'
        'prompt_user_intro = "intro\\n"\n'
        'target_language_name = "T"\n'
        'output_slug = "s"\n'
        'release_name = "Xx"\n'
        'description = "D"\n',
        encoding="utf-8",
    )


def test_code_mismatch_fails_loudly(tmp_path, monkeypatch):
    _write_minimal_toml(tmp_path / "assets" / "fr", "es")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="requested"):
        get_language("fr")


def test_unknown_field_fails_loudly(tmp_path, monkeypatch):
    _write_minimal_toml(tmp_path / "assets" / "fr", "fr")
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "assets" / "fr" / "dict.toml", "a", encoding="utf-8") as f:
        f.write('bogus = "x"\n')
    with pytest.raises(ValueError, match="unknown field"):
        get_language("fr")


def test_resolve_paths_uses_data_lang_layout():
    paths = resolve_paths("fr", repo_root=".")
    assert paths.base == Path("data/fr/cfdict.u8")
    assert paths.human == Path("data/fr/human.u8")
    assert paths.llm_generated == Path("data/fr/llm_generated.json")
    assert paths.cc_cedict == Path("data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz")
    assert paths.out_human == Path("output/fr/cfdict-next-human.u8")
    assert paths.out_full == Path("output/fr/cfdict-next-full.u8")
    assert paths.scope_out == Path("output/fr/scope.md")


def test_resolve_paths_hsk3_layout():
    paths = resolve_paths("zh-CN-HSK03", repo_root=".")
    # No authoritative base for HSK3: base resolves to None.
    assert paths.base is None
    assert paths.human == Path("data/zh-CN-HSK03/human.u8")
    assert paths.llm_generated == Path("data/zh-CN-HSK03/llm_generated.json")
    assert paths.out_human == Path("output/zh-CN-HSK03/hsk3-next-human.u8")
    assert paths.out_full == Path("output/zh-CN-HSK03/hsk3-next-full.u8")
    # CC-CEDICT scope is shared across languages, not per-lang.
    assert paths.cc_cedict == Path("data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz")


def test_hsk3_explicit_base_override_still_applies(tmp_path):
    paths = resolve_paths("zh-CN-HSK03", repo_root=tmp_path, base=tmp_path / "base.u8")
    assert paths.base == tmp_path / "base.u8"


def test_empty_string_override_counts_as_not_given(tmp_path):
    paths = resolve_paths("fr", repo_root=tmp_path, base="")
    assert paths.base == tmp_path / "data" / "fr" / "cfdict.u8"


def test_explicit_overrides_win_over_language_defaults(tmp_path):
    paths = resolve_paths(
        "fr",
        repo_root=tmp_path,
        base=tmp_path / "custom-base.u8",
        human=tmp_path / "custom-human.u8",
    )
    assert paths.base == tmp_path / "custom-base.u8"
    assert paths.human == tmp_path / "custom-human.u8"
    # Non-overridden paths still resolve under the given repo root.
    assert paths.llm_generated == tmp_path / "data" / "fr" / "llm_generated.json"
