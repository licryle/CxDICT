"""Tests for scope vocabulary and membership (src/cxdict/scope.py)."""

import pytest

from cxdict.parser.u8 import DictionaryEntry
from cxdict.scope import SCOPES, check_scope, latest_valid_llm_ids


def entry(trad, simp, pin, defs=("d",)):
    return DictionaryEntry(
        traditional=trad, simplified=simp, pinyin=pin, definitions=tuple(defs)
    )


def record(trad, simp, pin, glosses=("d",)):
    return {
        "traditional": trad, "simplified": simp, "pinyin": pin,
        "senses": [{"source_gloss": g, "definition": "x"} for g in glosses],
        "cc_cedict_version": "cc-cedict:2026-09-12:abcdef123456",
        "llm_model": "m", "prompt_version": "p",
        "generation_date": "2026-01-01T00:00:00+00:00",
    }


def test_scopes_vocabulary_and_check():
    assert set(SCOPES) == {"superscope", "latest"}
    assert check_scope("latest") == "latest"
    with pytest.raises(ValueError):
        check_scope("nonsense")


def test_latest_valid_llm_ids():
    entries = [entry("K", "K", "P1", ("a", "b")), entry("N", "N", "NG", ("c",))]
    glosses = {e.lexical_id(): set(e.definitions) for e in entries}
    llm = {
        "K|K|P1": record("K", "K", "P1", ("a", "b")),
        "N|N|NG": record("N", "N", "NG", ("stale",)),
        "Z|Z|P7": record("Z", "Z", "P7", ("gone",)),
    }
    assert latest_valid_llm_ids(llm, glosses) == {"K|K|P1"}
