"""Unit tests for scope computation (src/scope.py, spec §3, §10, §12)."""

from cxdict.identity import compute_lexical_identity
from cxdict.scope import (
    compute_full_scope,
    compute_human_scope,
    compute_missing_scope,
    compute_scope_statistics,
)


def _id(trad, simp, pin):
    return compute_lexical_identity(trad, simp, pin)


# Fixture scenario:
#   CC-CEDICT: A, B, C, D
#   base:      A          (authoritative, wins)
#   human:     B          (curated)
#   llm:       —
A = _id("國", "国", "Guo2")
B = _id("中", "中", "Zhong1")
C = _id("行", "行", "Xing2")
D = _id("學", "学", "Xue2")


def test_missing_scope_excludes_base_and_existing_llm():
    missing = compute_missing_scope({A, B, C, D}, {A}, set(), {B})
    assert missing == {C, D}


def test_missing_scope_is_empty_when_fully_covered():
    assert compute_missing_scope({A, B}, {A, B}, set(), set()) == set()
    assert compute_missing_scope({A}, {A}, {A}, {A}) == set()


def test_human_entries_do_not_reenter_missing_scope():
    missing = compute_missing_scope({A, B, C}, {A}, {B}, set())
    assert missing == {C}


def test_llm_entries_do_not_reenter_missing_scope():
    missing = compute_missing_scope({A, B, C}, {A}, set(), {B})
    assert missing == {C}


def test_human_scope_is_base_plus_human():
    scope = compute_human_scope({A}, {B})
    assert scope == {A, B}
    # LLM content has no path into the human dictionary (spec §10.1):
    # compute_human_scope does not even accept llm ids.
    assert C not in compute_human_scope({A}, {B})


def test_full_scope_includes_llm():
    scope = compute_full_scope({A}, {B}, {C})
    assert scope == {A, B, C}


def test_scope_statistics_are_consistent():
    stats = compute_scope_statistics({A, B, C, D}, {A}, {B}, {C})
    assert stats["cc_cedict_total"] == 4
    assert stats["base_total"] == 1
    assert stats["human_total"] == 1
    assert stats["llm_generated_total"] == 1
    assert stats["missing_scope_total"] == 1  # only D
    assert stats["human_dictionary_total"] == 2  # A + B
    assert stats["full_dictionary_total"] == 3  # A + B + C
    assert stats["base_covers_cc_cedict"] == 1
    assert stats["human_dictionary_covers_cc_cedict"] == 2  # A + B
    assert stats["full_dictionary_covers_cc_cedict"] == 3  # A + B + C


def test_scope_statistics_track_out_of_cc_entries():
    outside = _id("外", "外", "Wai4")
    stats = compute_scope_statistics({A, B}, {A, outside}, {outside}, set())
    assert stats["base_total"] == 2
    assert stats["base_covers_cc_cedict"] == 1
    assert stats["human_dictionary_total"] == 2  # base + human overlap
    assert stats["human_dictionary_covers_cc_cedict"] == 1
    assert stats["full_dictionary_total"] == 2
    assert stats["full_dictionary_covers_cc_cedict"] == 1
