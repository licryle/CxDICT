"""Unit tests for the per-language registry (src/cfdict_next/languages.py, P0).

P0 is additive only: these tests pin the registry values and path
resolution without touching any existing pipeline behavior.
"""

from pathlib import Path

import pytest

from cfdict_next.languages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    get_language,
    resolve_paths,
)


def test_default_language_is_french_for_backward_compat():
    assert DEFAULT_LANGUAGE == "fr"
    assert get_language(DEFAULT_LANGUAGE).code == "fr"


def test_french_config_matches_current_pipeline_reality():
    fr = get_language("fr")
    assert fr.base_filename == "cfdict.u8"
    assert fr.base_label == "CFDICT"
    assert "generate_fr_v5" in fr.prompt_template
    assert fr.prompt_version == "v5"
    assert fr.definition_field == "french_definition"
    assert fr.output_slug == "cfdict"


def test_hsk3_config_has_no_base_and_own_definition_field():
    hsk = get_language("zh-CN-HSK03")
    assert hsk.base_filename is None
    assert hsk.base_url is None
    assert hsk.definition_field == "hsk3_definition"
    assert hsk.prompt_version == "v1"
    assert "HSK3" in hsk.description
    assert "HSK3" in hsk.target_language_name


def test_unknown_language_lists_available_codes():
    with pytest.raises(ValueError, match="zh-CN-HSK03"):
        get_language("xx-unknown")


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


def test_registry_codes_are_filesystem_safe():
    for code in LANGUAGES:
        assert code and "/" not in code and "\\" not in code
