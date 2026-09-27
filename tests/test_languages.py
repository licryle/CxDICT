"""Unit tests for the TOML-driven language registry (src/cxdict/languages.py).

Language definitions live outside the package in
dictionaries/<code>/dict.toml; these tests pin the loader behavior and
path resolution.
"""

from pathlib import Path

import pytest

from cxdict.languages import (
    CC_CEDICT_FALLBACK_FILE,
    get_language,
    resolve_cc_cedict,
    resolve_paths,
)

REPO = Path(__file__).resolve().parent.parent


def test_french_config_matches_current_pipeline_reality():
    fr = get_language("fr")
    assert fr.code == "fr"
    assert fr.base_filename == "cfdict.u8"
    assert fr.base_label == "CFDICT (Under license CC BY-SA 3.0)"
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
    assert fr.config_dir == REPO / "dictionaries" / "fr"


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
    _write_minimal_toml(tmp_path / "dictionaries" / "fr", "es")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="requested"):
        get_language("fr")


def test_unknown_field_fails_loudly(tmp_path, monkeypatch):
    _write_minimal_toml(tmp_path / "dictionaries" / "fr", "fr")
    monkeypatch.chdir(tmp_path)
    with open(tmp_path / "dictionaries" / "fr" / "dict.toml", "a", encoding="utf-8") as f:
        f.write('bogus = "x"\n')
    with pytest.raises(ValueError, match="unknown field"):
        get_language("fr")


def test_resolve_paths_uses_data_lang_layout():
    paths = resolve_paths("fr", repo_root=".")
    assert paths.base == Path("dictionaries/fr/data/cfdict.u8")
    assert paths.human == Path("dictionaries/fr/data/human.u8")
    assert paths.llm_generated == Path("dictionaries/fr/data/llm_generated.json")
    assert paths.cc_cedict == Path(
        "dictionaries/cc-cedict/2026-09-12.u8"
    )
    assert paths.out_human == Path("output/fr/cfdict-next-human.u8")
    assert paths.out_full == Path("output/fr/cfdict-next-full.u8")
    assert paths.scope_out == Path("output/fr/scope.md")


def test_resolve_paths_hsk3_layout():
    paths = resolve_paths("zh-CN-HSK03", repo_root=".")
    # No authoritative base for HSK3: base resolves to None.
    assert paths.base is None
    assert paths.human == Path("dictionaries/zh-CN-HSK03/data/human.u8")
    assert paths.llm_generated == Path(
        "dictionaries/zh-CN-HSK03/data/llm_generated.json"
    )
    assert paths.out_human == Path("output/zh-CN-HSK03/hsk3-next-human.u8")
    assert paths.out_full == Path("output/zh-CN-HSK03/hsk3-next-full.u8")
    # CC-CEDICT scope is shared across languages, not per-lang.
    assert paths.cc_cedict == Path(
        "dictionaries/cc-cedict/2026-09-12.u8"
    )


def test_hsk3_explicit_base_override_still_applies(tmp_path):
    paths = resolve_paths("zh-CN-HSK03", repo_root=tmp_path, base=tmp_path / "base.u8")
    assert paths.base == tmp_path / "base.u8"


def test_empty_string_override_counts_as_not_given(tmp_path):
    paths = resolve_paths("fr", repo_root=tmp_path, base="")
    assert paths.base == tmp_path / "dictionaries" / "fr" / "data" / "cfdict.u8"


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
    assert paths.llm_generated == (
        tmp_path / "dictionaries" / "fr" / "data" / "llm_generated.json"
    )


def test_repo_cc_cedict_dir_resolves_to_logged_latest():
    paths = resolve_paths("fr", repo_root=REPO)
    assert paths.cc_cedict_dir == REPO / "dictionaries" / "cc-cedict"
    # The logged latest snapshot, not a hardcoded filename.
    assert paths.cc_cedict == REPO / "dictionaries" / "cc-cedict" / "2026-09-12.u8"
    assert paths.cc_cedict.is_file()


def test_resolve_cc_cedict_prefers_manifest_then_dated_then_fallback(tmp_path):
    cc = tmp_path / "cc"
    cc.mkdir()
    # No log, no dated file: legacy fallback filename.
    assert resolve_cc_cedict(cc) == cc / CC_CEDICT_FALLBACK_FILE
    # Dated files, no log: newest by name (legacy tree).
    (cc / "2024-01-01.u8").write_text("", encoding="utf-8")
    (cc / "2026-09-12.u8").write_text("", encoding="utf-8")
    assert resolve_cc_cedict(cc) == cc / "2026-09-12.u8"
    # Log present: newest logged entry wins over any stray dated file.
    (cc / "2027-01-01.u8").write_text("", encoding="utf-8")
    (cc / "snapshots.toml").write_text(
        "[[snapshot]]\n"
        'date = "2024-01-01"\nfile = "2024-01-01.u8"\n'
        'upstream_date = "x"\nupstream_time = 0\n'
        'upstream_sha256 = ""\ncontent_sha256 = "a"\nentries = 0\npairs = 0\n'
        "[[snapshot]]\n"
        'date = "2026-09-12"\nfile = "2026-09-12.u8"\n'
        'upstream_date = "x"\nupstream_time = 1\n'
        'upstream_sha256 = ""\ncontent_sha256 = "b"\nentries = 0\npairs = 0\n',
        encoding="utf-8",
    )
    assert resolve_cc_cedict(cc) == cc / "2026-09-12.u8"


def test_resolve_cc_cedict_raises_on_corrupt_log(tmp_path):
    cc = tmp_path / "cc"
    cc.mkdir()
    (cc / "2026-09-12.u8").write_text("", encoding="utf-8")
    (cc / "snapshots.toml").write_text("this is not = valid = toml", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_cc_cedict(cc)


def test_explicit_cc_cedict_dir_and_file_win(tmp_path):
    paths = resolve_paths("fr", repo_root=tmp_path, cc_cedict_dir=tmp_path / "snap")
    assert paths.cc_cedict_dir == tmp_path / "snap"
    assert paths.cc_cedict == tmp_path / "snap" / CC_CEDICT_FALLBACK_FILE
    # An explicit file beats the directory entirely (fixture escape hatch).
    paths = resolve_paths(
        "fr", repo_root=tmp_path, cc_cedict_dir=tmp_path / "snap",
        cc_cedict=tmp_path / "snap" / "one.u8",
    )
    assert paths.cc_cedict == tmp_path / "snap" / "one.u8"


def test_english_scope_unit_loads_without_prompt_machinery():
    en = get_language("en")
    assert en.code == "en"
    assert en.base_filename is None
    assert en.scope_as_base is True
    assert en.generate is False
    assert en.prompt_template is None and en.few_shot is None
    assert en.release_name == "English"
    # Base resolves to none (built from scope at run time); outputs do not.
    paths = resolve_paths("en", repo_root=REPO)
    assert paths.base is None
    assert paths.out_human.name == "english-next-human.u8"
    assert paths.out_full.name == "english-next-full.u8"


def write_lang_toml(tmp_path, code, **fields):
    base = {
        "code": code,
        "base_label": "X",
        "target_language_name": "X",
        "output_slug": "x",
        "release_name": "X",
        "description": "X",
        "prompt_template": "p.txt",
        "few_shot": "f.json",
        "prompt_version": "v1",
        "prompt_user_intro": "hi",
    }
    base.update(fields)
    if base.get("generate") is False:
        for key in ("prompt_template", "few_shot", "prompt_version",
                    "prompt_user_intro"):
            base.pop(key, None)
    lang_dir = tmp_path / "dictionaries" / code
    lang_dir.mkdir(parents=True)
    lines = []
    for key, value in base.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        else:
            lines.append(f'{key} = "{value}"')
    (lang_dir / "dict.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lang_dir


def test_get_language_fixture_tree_rejects_bad_flags(tmp_path):
    write_lang_toml(tmp_path, "xx", generate="yes")
    with pytest.raises(ValueError):
        get_language("xx", repo_root=tmp_path)
    write_lang_toml(tmp_path, "yy", base_filename="b.u8", scope_as_base=True)
    with pytest.raises(ValueError):
        get_language("yy", repo_root=tmp_path)
    write_lang_toml(tmp_path, "zz", generate=False, scope_as_base=True)
    zz = get_language("zz", repo_root=tmp_path)
    assert zz.generate is False and zz.scope_as_base is True
    assert zz.prompt_template is None
