"""Golden tests: exact output bytes/content for assembly and scope notes.

These lock the release artifacts end to end on tiny fixtures: any change
to ordering, headers, formatting, or scope text fails here first.
"""

from cfdict_next.assembly import (
    HUMAN_SECTION_HEADER,
    LLM_SECTION_HEADER,
    assemble_files,
    section_header_for,
)
from cfdict_next.parser.u8 import DictionaryEntry
from cfdict_next.scope_info import (
    ReleaseSources,
    build_scope_info,
    render_scope_markdown,
)


def _entry(trad, simp, pinyin, definitions):
    return DictionaryEntry(
        traditional=trad, simplified=simp, pinyin=pinyin,
        definitions=tuple(definitions),
    )


def _u8_line(trad, simp, pinyin, definitions):
    return f"{trad} {simp} [{pinyin}] /{'/'.join(definitions)}/\n"


def _record(trad, simp, pinyin, glosses):
    return {
        "traditional": trad,
        "simplified": simp,
        "pinyin": pinyin,
        "senses": [
            {"source_gloss": g, "definition": f"def-{g}"} for g in glosses
        ],
        "cc_cedict_version": "v",
        "llm_model": "m",
        "prompt_version": "p",
        "generation_date": "2025-01-01T00:00:00+00:00",
    }


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def test_fr_assembly_golden_bytes(tmp_path):
    import json

    base_p = _write(
        tmp_path / "base.u8",
        _u8_line("中國", "中国", "Zhong1 guo2", ["Chine"]),
    )
    human_p = _write(
        tmp_path / "human.u8", _u8_line("美", "美", "Mei3", ["beau"])
    )
    llm_p = _write(
        tmp_path / "llm.json",
        json.dumps(
            {"行|行|Xing2": _record("行", "行", "Xing2", ["to walk"])},
            ensure_ascii=False,
        ),
    )
    out_c, out_f = tmp_path / "c.u8", tmp_path / "f.u8"
    assert assemble_files(base_p, human_p, llm_p, out_c, out_f, "fr") == (2, 3)
    assert out_c.read_text(encoding="utf-8") == (
        section_header_for("fr") + "\n"
        + _u8_line("中國", "中国", "Zhong1 guo2", ["Chine"])
        + HUMAN_SECTION_HEADER + "\n"
        + _u8_line("美", "美", "Mei3", ["beau"])
    )
    assert out_f.read_text(encoding="utf-8") == (
        section_header_for("fr") + "\n"
        + _u8_line("中國", "中国", "Zhong1 guo2", ["Chine"])
        + HUMAN_SECTION_HEADER + "\n"
        + _u8_line("美", "美", "Mei3", ["beau"])
        + LLM_SECTION_HEADER + "\n"
        + _u8_line("行", "行", "Xing2", ["def-to walk"])
    )


def test_hsk3_assembly_omits_base_section(tmp_path):
    import json

    human_p = _write(
        tmp_path / "human.u8", _u8_line("美", "美", "Mei3", ["很美"])
    )
    llm_p = _write(
        tmp_path / "llm.json",
        json.dumps(
            {"行|行|Xing2": _record("行", "行", "Xing2", ["to walk"])},
            ensure_ascii=False,
        ),
    )
    out_c, out_f = tmp_path / "c.u8", tmp_path / "f.u8"
    assert assemble_files(None, human_p, llm_p, out_c, out_f, "zh-CN-HSK03") == (1, 2)
    assert out_c.read_text(encoding="utf-8") == (
        HUMAN_SECTION_HEADER + "\n"
        + _u8_line("美", "美", "Mei3", ["很美"])
    )
    assert out_f.read_text(encoding="utf-8") == (
        HUMAN_SECTION_HEADER + "\n"
        + _u8_line("美", "美", "Mei3", ["很美"])
        + LLM_SECTION_HEADER + "\n"
        + _u8_line("行", "行", "Xing2", ["def-to walk"])
    )


def test_scope_markdown_golden_text():
    sources = ReleaseSources(
        cc_cedict_version="cc-v1",
        cc_cedict_ids={"A", "B", "C", "D"},
        base_version="base-v1",
        base_ids={"A"},
        human_version="human-v1",
        human_ids={"B"},
        llm_generated_version="llm-v1",
        llm_generated_ids={"C"},
        llm_models=("m1",),
        prompt_versions=("p1",),
    )
    markdown = render_scope_markdown(
        build_scope_info(sources, generated_at="T"), "CFDICT"
    )
    assert markdown == (
        "## Scope\n"
        "\n"
        "Generated at T.\n"
        "\n"
        "| source | version | entries |\n"
        "| --- | --- | --- |\n"
        "| CC-CEDICT (scope) | cc-v1 | 4 |\n"
        "| CFDICT (authoritative) | base-v1 | 1 |\n"
        "| Human (curated) | human-v1 | 1 |\n"
        "| LLM generated | llm-v1 | 1 |\n"
        "\n"
        "## Coverage\n"
        "\n"
        "- Missing scope (still to generate): 1\n"
        "- Human dictionary: 2 entries\n"
        "- Full dictionary: 3 entries\n"
        "- CFDICT covers 1 CC-CEDICT entries\n"
        "- Human covers 1 CC-CEDICT entries\n"
        "- LLM covers 1 CC-CEDICT entries\n"
        "\n"
        "## Provenance\n"
        "\n"
        "- LLM models: m1\n"
        "- Prompt versions: p1\n"
    )
