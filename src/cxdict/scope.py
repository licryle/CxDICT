"""Scope computation for dictionary generation (spec §3, §10, §12).

Missing generation scope:  CC-CEDICT − base − human.u8 − llm_generated.json
Human dictionary:          base + human.u8
Full dictionary:           base + human.u8 + llm_generated.json

CC-CEDICT, base and human.u8 arrive as parsed lists of DictionaryEntry;
the LLM dataset arrives as a mapping of lexical identity -> record (see
cxdict.parser.json.load_llm_json). All sources meet at the same
lexical identity (spec §15), which is what makes the set arithmetic valid.
"""

from __future__ import annotations


def compute_missing_scope(
    cc_cedict_ids: set[str],
    base_ids: set[str],
    human_ids: set[str],
    llm_ids: set[str],
) -> set[str]:
    """Return the identities still needing LLM generation.

    CC-CEDICT minus everything already covered by the authoritative
    dictionary, human curation, or existing LLM output (spec §3, §5).
    """
    return (
        set(cc_cedict_ids)
        - set(base_ids)
        - set(human_ids)
        - set(llm_ids)
    )


def compute_human_scope(
    base_ids: set[str],
    human_ids: set[str],
) -> set[str]:
    """Return the identities included in the human dictionary (spec §10.1)."""
    return set(base_ids) | set(human_ids)


def compute_full_scope(
    base_ids: set[str],
    human_ids: set[str],
    llm_ids: set[str],
) -> set[str]:
    """Return the identities included in the full dictionary (spec §10.2)."""
    return set(base_ids) | set(human_ids) | set(llm_ids)


def compute_scope_statistics(
    cc_cedict_ids: set[str],
    base_ids: set[str],
    human_ids: set[str],
    llm_ids: set[str],
) -> dict[str, int]:
    """Return coverage counts for the release scope information (spec §12)."""
    missing = compute_missing_scope(cc_cedict_ids, base_ids, human_ids, llm_ids)
    human_scope = compute_human_scope(base_ids, human_ids)
    full_scope = compute_full_scope(base_ids, human_ids, llm_ids)
    in_cc = set(cc_cedict_ids)
    base_in_cc = len(set(base_ids) & in_cc)
    human_in_cc = len(set(human_ids) & in_cc)
    llm_in_cc = len(set(llm_ids) & in_cc)
    human_dict_in_cc = len(human_scope & in_cc)
    full_dict_in_cc = len(full_scope & in_cc)
    return {
        "cc_cedict_total": len(cc_cedict_ids),
        "base_total": len(base_ids),
        "human_total": len(human_ids),
        "llm_generated_total": len(llm_ids),
        "missing_scope_total": len(missing),
        "human_dictionary_total": len(human_scope),
        "full_dictionary_total": len(full_scope),
        "base_covers_cc_cedict": base_in_cc,
        "human_covers_cc_cedict": human_in_cc,
        "llm_covers_cc_cedict": llm_in_cc,
        "human_dictionary_covers_cc_cedict": human_dict_in_cc,
        "full_dictionary_covers_cc_cedict": full_dict_in_cc,
    }
