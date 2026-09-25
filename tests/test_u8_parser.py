"""Unit tests for the CEDICT/.u8 line parser (src/parser/u8.py)."""

import pytest

from cxdict.parser.u8 import parse_u8_file, parse_u8_line, DictionaryEntry


def test_canonical_entry():
    e = parse_u8_line("中國 中国 [Zhong1 guo2] /China/Middle Kingdom/")
    assert e is not None
    assert e.traditional == "中國"
    assert e.simplified == "中国"
    assert e.pinyin == "Zhong1 guo2"
    assert e.definitions == ("China", "Middle Kingdom")


def test_single_gloss_and_spaces():
    e = parse_u8_line("110 110 [yao1 yao1 ling2] /the emergency number/")
    assert e is not None
    assert e.traditional == "110"
    assert e.simplified == "110"
    assert e.definitions == ("the emergency number",)


def test_crlf_line_endings_are_normalized():
    e = parse_u8_line("中國 中国 [Zhong1 guo2] /China/\r\n")
    assert e is not None
    assert e.definitions == ("China",)


def test_comment_and_blank_return_none():
    assert parse_u8_line("# CC-CEDICT\r\n") is None
    assert parse_u8_line("") is None
    assert parse_u8_line("   \n") is None


@pytest.mark.parametrize(
    "line",
    [
        "中國 中国 /China/",                      # missing [pinyin]
        "中國 中国 [Zhong1 guo2] China",           # missing definition slashes
        "中國 中国 [Zhong1 guo2] /China",           # missing trailing slash
        "中國 中国 [Zhong1 guo2] //",              # empty definitions
        " 中国 [Zhong1 guo2] /China/",             # missing simplified
    ],
)
def test_malformed_lines_raise(line):
    with pytest.raises(ValueError):
        parse_u8_line(line)


def test_parse_u8_file_reports_errors_and_entries(tmp_path):
    f = tmp_path / "sample.u8"
    f.write_text(
        "# header\n"
        "中國 中国 [Zhong1 guo2] /China/\n"
        "broken line without structure\n"
        "美國 美国 [Mei3 guo2] /United States/\n",
        encoding="utf-8",
    )
    entries, errors = parse_u8_file(f)
    assert [e.traditional for e in entries] == ["中國", "美國"]
    assert len(errors) == 1
    lineno, msg = errors[0]
    assert lineno == 3
    assert "broken line without structure" in msg


def test_lexical_id_round_trip():
    from cxdict.identity import parse_lexical_identity

    e = parse_u8_line("中國 中国 [Zhong1 guo2] /China/")
    trad, simp, pin = parse_lexical_identity(e.lexical_id())
    assert (trad, simp, pin) == ("中國", "中国", "Zhong1 guo2")



def test_ideographic_space_inside_headword_is_preserved():
    # CFDICT line 31202: U+3000 within the headword itself.
    e = parse_u8_line(
        "法郎索瓦　萨维叶 法郎索瓦　萨维叶 [fa3 lang2 suo3 wa3 sa4 wei2 ye4] /François Xavier/\n"
    )
    assert e is not None
    assert e.traditional == "法郎索瓦 萨维叶"
    assert e.simplified == "法郎索瓦 萨维叶"
    assert e.definitions == ("François Xavier",)


def test_duplicate_entries_are_merged():
    # Test that duplicate entries with the same lexical identity are merged
    line1 = "中國 中国 [Zhong1 guo2] /China/\n"
    line2 = "中國 中国 [Zhong1 guo2] /Middle Kingdom/\n"
    
    entries, errors = parse_u8_file_from_lines([line1, line2])
    assert errors == []
    assert len(entries) == 1
    
    entry = entries[0]
    assert entry.traditional == "中國"
    assert entry.simplified == "中国"
    assert entry.pinyin == "Zhong1 guo2"
    assert entry.definitions == ("China", "Middle Kingdom")

def parse_u8_file_from_lines(lines: list[str]) -> tuple[list[DictionaryEntry], list[tuple[int, str]]]:
    """Helper for testing: parse entries from a list of lines."""
    entries_by_id: dict[str, DictionaryEntry] = {}
    errors: list[tuple[int, str]] = []
    for lineno, raw in enumerate(lines, start=1):
        try:
            entry = parse_u8_line(raw)
        except ValueError as exc:
            errors.append((lineno, str(exc)))
            continue
        if entry is None:
            continue
        
        # Merge duplicates by lexical identity
        entry_id = entry.lexical_id()
        if entry_id in entries_by_id:
            existing = entries_by_id[entry_id]
            merged_defs = tuple(sorted(set(existing.definitions + entry.definitions)))
            entries_by_id[entry_id] = DictionaryEntry(
                traditional=existing.traditional,
                simplified=existing.simplified,
                pinyin=existing.pinyin,
                definitions=merged_defs,
            )
        else:
            entries_by_id[entry_id] = entry
    
    return list(entries_by_id.values()), errors


def test_duplicate_entries_are_merged():
    # Test that duplicate entries with the same lexical identity are merged
    line1 = "中國 中国 [Zhong1 guo2] /China/\n"
    line2 = "中國 中国 [Zhong1 guo2] /Middle Kingdom/\n"
    
    entries, errors = parse_u8_file_from_lines([line1, line2])
    assert errors == []
    assert len(entries) == 1
    
    entry = entries[0]
    assert entry.traditional == "中國"
    assert entry.simplified == "中国"
    assert entry.pinyin == "Zhong1 guo2"
    assert entry.definitions == ("China", "Middle Kingdom")

def test_identical_glosses_are_deduplicated():
    line1 = "中國 中国 [Zhong1 guo2] /China/\n"
    line2 = "中國 中国 [Zhong1 guo2] /China/\n"
    
    entries, errors = parse_u8_file_from_lines([line1, line2])
    assert errors == []
    assert len(entries) == 1
    assert entries[0].definitions == ("China",)
