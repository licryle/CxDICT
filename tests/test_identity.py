"""Unit tests for lexical identity (src/identity.py, spec §15)."""

import pytest

from cxdict.identity import compute_lexical_identity, parse_lexical_identity


def test_identity_combines_three_parts():
    assert (
        compute_lexical_identity("中國", "中国", "Zhong1 guo2")
        == "中國|中国|Zhong1 guo2"
    )


def test_identity_is_deterministic_and_whitespace_insensitive():
    a = compute_lexical_identity("中國", "中国", "Zhong1 guo2")
    b = compute_lexical_identity(" 中國 ", "中国 ", " Zhong1 guo2 ")
    assert a == b


def test_same_characters_different_pinyin_are_distinct():
    # 行 háng (row) vs xíng (to walk) — spec §15 requires distinct identities.
    hang = compute_lexical_identity("行", "行", "Hang2")
    xing = compute_lexical_identity("行", "行", "Xing2")
    assert hang != xing


def test_empty_pinyin_is_allowed_but_empty_characters_are_not():
    assert compute_lexical_identity("中國", "中国", "") == "中國|中国|"
    with pytest.raises(ValueError):
        compute_lexical_identity("", "中国", "Zhong1")
    with pytest.raises(ValueError):
        compute_lexical_identity("中國", "", "Zhong1")


def test_round_trip():
    ident = compute_lexical_identity("銀行", "银行", "Yin2 hang2")
    assert parse_lexical_identity(ident) == ("銀行", "银行", "Yin2 hang2")


def test_parse_rejects_malformed_identity():
    with pytest.raises(ValueError):
        parse_lexical_identity("no-separators-here")
