"""Tests for dictionary assembly (Phase 7, spec §10, §14, §15).

Covers precedence and fail-loud overlaps, output ordering, the U+3000
write-back rule, lossless parser/writer round-trips over both real
datasets, determinism, and the CLI.
"""

import json
import re
from pathlib import Path

import pytest

from cfdict_next.assembly import (
    HUMAN_SECTION_HEADER,
    LLM_SECTION_HEADER,
    assemble,
    assemble_files,
    assemble_sections,
    format_u8_entry,
    record_to_entry,
    section_header_for,
    write_sectioned_u8_file,
    write_u8_file,
)
from cfdict_next.parser.u8 import DictionaryEntry, iter_u8_lines, parse_u8_line, parse_u8_file

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "data" / "fr" / "cfdict.u8"
CEDICT_GZ = REPO / "data" / "cc-cedict" / "cedict_1_0_ts_utf-8_mdbg.txt.gz"


def entry(trad="中國", simp="中国", pin="Zhong1 guo2", defs=("Chine",)):
    return DictionaryEntry(traditional=trad, simplified=simp, pinyin=pin, definitions=defs)


def llm_record_for(key, senses=(("China", "Chine"),)):
    """Build an LLM record whose identity fields match its key."""
    trad, simp, pin = key.split("|")
    return {
        "traditional": trad,
        "simplified": simp,
        "pinyin": pin,
        "senses": [
            {"source_gloss": g, "definition": d} for g, d in senses
        ],
        "cc_cedict_version": "v",
        "llm_model": "m",
        "prompt_version": "p",
        "generation_date": "2025-01-01T00:00:00+00:00",
    }


def llm_record(senses=(("China", "Chine"),)):
    return llm_record_for("美|美|Mei3", senses)


def test_base_always_wins_and_overlap_raises():
    base = [entry()]
    human = [entry()]
    with pytest.raises(ValueError, match="overlap base"):
        assemble(base, human, {})
    llm = {"中國|中国|Zhong1 guo2": llm_record()}
    with pytest.raises(ValueError, match="overlap base"):
        assemble(base, [], llm)


def test_human_beats_llm_and_overlap_raises():
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {"美|美|Mei3": llm_record()}
    with pytest.raises(ValueError, match="overlap base/human"):
        assemble([], human, llm)


def test_llm_overlapping_base_raises():
    base = [entry()]
    llm = {"中國|中国|Zhong1 guo2": llm_record()}
    with pytest.raises(ValueError, match="overlap base/human"):
        assemble(base, [], llm)


def test_human_dict_excludes_llm_full_includes_it():
    base = [entry()]
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {"好|好|Hao3": llm_record_for("好|好|Hao3")}
    human_entries, full_entries = assemble(base, human, llm)
    assert [e.lexical_id() for e in human_entries] == [
        "中國|中国|Zhong1 guo2",
        "美|美|Mei3",
    ]
    assert [e.lexical_id() for e in full_entries] == [
        "中國|中国|Zhong1 guo2",
        "美|美|Mei3",
        "好|好|Hao3",
    ]
    assert full_entries[2].definitions == ("Chine",)


def test_order_is_base_then_human_then_sorted_llm():
    base = [entry("中", "中", "Zhong1", ("milieu",)), entry()]
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {
        "行|行|Xing2": llm_record_for("行|行|Xing2"),
        "好|好|Hao3": llm_record_for("好|好|Hao3"),
    }
    human_entries, _ = assemble(base, human, llm)
    assert [e.simplified for e in human_entries] == ["中", "中国", "美"]
    _, full = assemble(base, human, llm)
    assert [e.simplified for e in full] == ["中", "中国", "美", "好", "行"]


def test_record_to_entry_preserves_sense_order():
    record = llm_record(senses=(("b", "B"), ("a", "A")))
    e = record_to_entry("美|美|Mei3", record)
    assert e.definitions == ("B", "A")


def test_format_restores_u3000():
    # Real CFDICT line 31202: the writer must put back the U+3000 the
    # parser normalizes (user rule: parser/writer are careful).
    raw = "法郎索瓦　萨维叶 法郎索瓦　萨维叶 [fa3 lang2 suo3 wa3 sa4 wei2 ye4] /François Xavier/\n"
    assert format_u8_entry(parse_u8_line(raw)) == raw


def test_real_files_round_trip_without_loss():
    # Definitions are strip-normalized on parse (20 CFDICT lines carry
    # "/ " separators or "//" empties; CC-CEDICT has none), so two
    # properties are asserted instead of naive byte equality:
    #  1. parse -> format -> parse is idempotent for EVERY entry line
    #     (the writer loses no information), and
    #  2. format(parse(line)) is byte-exact for every clean line —
    #     including the U+3000 headword the writer must restore.
    for path in (BASE, CEDICT_GZ):
        seen: set[str] = set()
        dup_ids: set[str] = set()
        checked = exact = quirks = 0
        for raw in iter_u8_lines(path):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            e = parse_u8_line(raw)
            assert e is not None
            # Idempotence for every line, duplicates included.
            assert parse_u8_line(format_u8_entry(e)) == e, f"{path}:{line[:40]}"
            ident = e.lexical_id()
            if ident in seen:
                dup_ids.add(ident)
                continue
            seen.add(ident)
            checked += 1
            # Quirk scope: a line needs separator-whitespace normalization
            # iff any definition segment differs from its stripped self
            # (covers "/ ", " /", "//" and non-breaking spaces) or is empty,
            # or the head/pinyin region uses runs of spaces or tabs.
            defs_start = line.find("/", line.find("]"))
            inner = line[defs_start + 1 : line.rfind("/")]
            segments = inner.split("/")
            head = line[: line.find("[")]
            if (
                any(s != s.strip() or not s for s in segments)
                or re.search(r"[ \t]{2,}", head)
                or "\t" in line
            ):
                quirks += 1
                continue
            assert format_u8_entry(e) == line + "\n", f"{path}:{line[:40]}"
            exact += 1
        assert checked > 50_000, path
        assert len(dup_ids) < 100, f"unexpected duplicate surge in {path}"
        # Every first-occurrence line is either byte-exact or a known quirk.
        assert exact + quirks == checked


def test_assemble_is_deterministic(tmp_path):
    base = [entry(), entry("中", "中", "Zhong1", ("milieu",))]
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {"好|好|Hao3": llm_record_for("好|好|Hao3")}
    out1_c, out1_f = tmp_path / "c1.u8", tmp_path / "f1.u8"
    out2_c, out2_f = tmp_path / "c2.u8", tmp_path / "f2.u8"
    ce, fe = assemble(base, human, llm)
    write_u8_file(out1_c, ce)
    write_u8_file(out1_f, fe)
    ce2, fe2 = assemble(base, human, llm)
    write_u8_file(out2_c, ce2)
    write_u8_file(out2_f, fe2)
    assert out1_c.read_bytes() == out2_c.read_bytes()
    assert out1_f.read_bytes() == out2_f.read_bytes()


def test_assemble_files_with_empty_llm_round_trips_base(tmp_path):
    # No human/LLM data: both outputs equal CFDICT content modulo dup-merge +
    # newline normalization — verified entry by entry.
    out_c = tmp_path / "human.u8"
    out_f = tmp_path / "full.u8"
    (tmp_path / "h.u8").write_text("", encoding="utf-8")
    (tmp_path / "l.json").write_text("{}", encoding="utf-8")
    human_n, full_n = assemble_files(
        BASE, tmp_path / "h.u8", tmp_path / "l.json", out_c, out_f, "fr"
    )
    assert human_n == full_n
    source_entries, errors = parse_u8_file(BASE)
    assert errors == []
    out_entries, out_errors = parse_u8_file(out_c)
    assert out_errors == []
    assert [e.lexical_id() for e in out_entries] == [
        e.lexical_id() for e in source_entries
    ]
    assert [e.definitions for e in out_entries] == [
        e.definitions for e in source_entries
    ]


def test_outputs_carry_section_headers_in_order(tmp_path):
    base = [entry()]
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {"好|好|Hao3": llm_record_for("好|好|Hao3")}
    c, f = tmp_path / "c.u8", tmp_path / "f.u8"
    (tmp_path / "l.json").write_text(json.dumps(llm), encoding="utf-8")
    (tmp_path / "h.u8").write_text(
        format_u8_entry(human[0]), encoding="utf-8"
    )
    (tmp_path / "cfdict.u8").write_text(
        format_u8_entry(entry()), encoding="utf-8"
    )
    assemble_files(tmp_path / "cfdict.u8", tmp_path / "h.u8",
                     tmp_path / "l.json", c, f, "fr")
    c_lines = c.read_text(encoding="utf-8").splitlines()
    assert c_lines[0] == section_header_for("fr")
    assert c_lines[2] == HUMAN_SECTION_HEADER
    assert LLM_SECTION_HEADER not in c_lines
    f_lines = f.read_text(encoding="utf-8").splitlines()
    assert f_lines[0] == section_header_for("fr")
    assert f_lines[2] == HUMAN_SECTION_HEADER
    assert f_lines[4] == LLM_SECTION_HEADER
    # Headers parse as comments: entry content is unchanged.
    out_entries, errors = parse_u8_file(f)
    assert errors == []
    assert [e.lexical_id() for e in out_entries] == [
        "中國|中国|Zhong1 guo2", "美|美|Mei3", "好|好|Hao3",
    ]


def test_empty_sections_omit_their_header(tmp_path):
    out = tmp_path / "o.u8"
    write_sectioned_u8_file(out, [
        (section_header_for("fr"), [entry()]),
        (HUMAN_SECTION_HEADER, []),
        (LLM_SECTION_HEADER, []),
    ])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == [section_header_for("fr"), format_u8_entry(entry()).strip()]


def test_section_header_comes_from_registry():
    assert section_header_for("fr") == (
        "# CFDICT Authoritative entries "
        "(from https://chine.in/mandarin/dictionnaire/CFDICT/)"
    )
    assert section_header_for("zh-CN-HSK03") == "# HSK3 base Authoritative entries"


def test_assemble_files_without_base_omits_base_section(tmp_path):
    out_c, out_f = tmp_path / "c.u8", tmp_path / "f.u8"
    (tmp_path / "h.u8").write_text(
        format_u8_entry(entry("美", "美", "Mei3", ("beau",))), encoding="utf-8"
    )
    (tmp_path / "l.json").write_text("{}", encoding="utf-8")
    human_n, full_n = assemble_files(
        None, tmp_path / "h.u8", tmp_path / "l.json", out_c, out_f, "zh-CN-HSK03"
    )
    assert (human_n, full_n) == (1, 1)
    assert out_c.read_text(encoding="utf-8").splitlines()[0] == HUMAN_SECTION_HEADER


def test_cli_requires_language(tmp_path):
    import pytest

    from cfdict_next.cli.assemble import main as cli_main

    with pytest.raises(SystemExit):
        cli_main(["--base", str(tmp_path / "cfdict.u8")])
    assert cli_main(["--language", "xx-unknown", "--base", str(tmp_path / "cfdict.u8")]) == 1


def test_sections_match_assemble_splits():
    base = [entry()]
    human = [entry("美", "美", "Mei3", ("beau",))]
    llm = {"好|好|Hao3": llm_record_for("好|好|Hao3")}
    c, he, le = assemble_sections(base, human, llm)
    assert c == base
    assert [e.lexical_id() for e in he] == ["美|美|Mei3"]
    assert [e.lexical_id() for e in le] == ["好|好|Hao3"]
    flat_c, flat_f = assemble(base, human, llm)
    assert flat_c == c + he and flat_f == c + he + le


def test_cli_smoke(tmp_path, capsys):
    from cfdict_next.cli.assemble import main as cli_main

    c = tmp_path / "cfdict.u8"
    c.write_text("中國 中国 [Zhong1 guo2] /Chine/\n", encoding="utf-8")
    h = tmp_path / "h.u8"
    h.write_text("", encoding="utf-8")
    (tmp_path / "l.json").write_text("{}", encoding="utf-8")
    rc = cli_main(
        [
            "--language", "fr", "--base", str(c),
            "--human", str(h),
            "--llm-generated", str(tmp_path / "l.json"),
            "--out-human", str(tmp_path / "o_c.u8"),
            "--out-full", str(tmp_path / "o_f.u8"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "o_c.u8").read_text(encoding="utf-8") == (
        (tmp_path / "o_f.u8").read_text(encoding="utf-8")
    )
    assert "human 1 entries" in capsys.readouterr().out
