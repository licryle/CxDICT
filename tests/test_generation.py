"""Tests for the LLM generation pipeline (Phase 5, spec §5, §6, §8).

Entry-level prompts: one entry (full gloss list) in, one record (full
sense list) out. No network: the HTTP layer is injected as a fake. Covers
config parsing, prompt rendering, batch validation/mapping/parity/retries,
record building with provenance, merging, and atomic writes
(round-tripped through the real Phase 3 loader).
"""

import json

import pytest

from cfdict_next.generation.config import (
    ConfigError,
    LLMConfig,
    load_config,
)
from cfdict_next.generation.llm import (
    GenerationError,
    GenerationItem,
    Sense,
    generate_batch,
)
from cfdict_next.generation.output import (
    Provenance,
    build_records,
    merge_records,
    write_llm_json,
)
from cfdict_next.generation.prompt import PROMPT_VERSION, render_prompt
from cfdict_next.parser.json import load_llm_json


def make_config(**overrides):
    args = {
        "endpoint": "http://test:1234/v1/chat/completions",
        "model": "test-model",
        "batch_size": 10,
        "max_retries": 1,
        "timeout_s": 5.0,
    }
    args.update(overrides)
    return LLMConfig(**args)


def make_items():
    return [
        GenerationItem(
            key="中國|中国|Zhong1 guo2",
            traditional="中國",
            simplified="中国",
            pinyin="Zhong1 guo2",
            glosses=("China", "Middle Kingdom"),
        ),
        GenerationItem(
            key="行|行|Xing2",
            traditional="行",
            simplified="行",
            pinyin="Xing2",
            glosses=("to walk",),
        ),
    ]


def chat_body(objects):
    return {"choices": [{"message": {"content": json.dumps(objects)}}]}


# --- config ---


def test_dotenv_parsing(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        "LLM_API_ENDPOINT=http://192.168.2.147:1234/v1/chat/completions\n"
        'LLM_MODEL_NAME="qwen/qwen2.5-vl-7b"\n'
        "LLM_BATCH_SIZE=5\n",
        encoding="utf-8",
    )
    cfg = load_config(env_path=f, environ={})
    assert cfg.endpoint == "http://192.168.2.147:1234/v1/chat/completions"
    assert cfg.model == "qwen/qwen2.5-vl-7b"
    assert cfg.batch_size == 5
    assert cfg.max_retries == 2  # default
    assert cfg.timeout_s == 120.0  # default


def test_config_missing_required_names_the_missing(tmp_path):
    f = tmp_path / ".env"
    f.write_text("LLM_MODEL_NAME=x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="LLM_API_ENDPOINT"):
        load_config(env_path=f, environ={})


def test_config_rejects_bad_values(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "LLM_API_ENDPOINT=not-a-url\nLLM_MODEL_NAME=x\nLLM_BATCH_SIZE=0\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="http"):
        load_config(env_path=f, environ={})


def test_config_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(env_path=tmp_path / "nope.env", environ={})


def test_environ_overrides_dotenv(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "LLM_API_ENDPOINT=http://file:1/x\nLLM_MODEL_NAME=file-model\n",
        encoding="utf-8",
    )
    cfg = load_config(env_path=f, environ={"LLM_MODEL_NAME": "env-model"})
    assert cfg.model == "env-model"
    assert cfg.endpoint == "http://file:1/x"


# --- prompt ---


def test_render_lists_whole_gloss_lists_per_entry():
    system, user = render_prompt(make_items(), "fr")
    assert "{example_lines}" not in system
    assert "lexicography" in system
    assert '[0] 中国 (中國, Zhong1 guo2) — senses:' in user
    assert '"China"' in user and '"Middle Kingdom"' in user
    assert '[1] 行 (行, Xing2) — senses:' in user


def test_prompt_version_is_pinned():
    assert PROMPT_VERSION == "v6"


def test_few_shot_examples_pass_the_real_validator():
    # The examples shown to the model must themselves be valid prompt /
    # response pairs — otherwise we teach the model our own mistakes.
    from cfdict_next.generation.prompt import EXAMPLE_ITEMS, EXAMPLE_OUTPUTS

    def fake_post(endpoint, model, system, user, timeout_s):
        for item, output in zip(EXAMPLE_ITEMS, EXAMPLE_OUTPUTS):
            assert f"[{output['id']}] {item.simplified}" in user
        return chat_body(EXAMPLE_OUTPUTS)

    outcome = generate_batch(
        list(EXAMPLE_ITEMS), make_config(max_retries=0), language="fr", post=fake_post
    )
    assert outcome.failed == []
    assert len(outcome.results) == 16
    assert sum(len(r.senses) for r in outcome.results) == 27


def test_few_shot_file_is_self_consistent():
    # Every curated example splits to equal gloss/definition segment counts
    # (checked at load), and identities match the file's own fields.
    import json
    from pathlib import Path

    from cfdict_next.generation import prompt as prompt_module
    from cfdict_next.identity import compute_lexical_identity
    from cfdict_next.languages import LANGUAGES

    for code, cfg in LANGUAGES.items():
        few_shot = Path(prompt_module.__file__).parent / "assets" / cfg.few_shot
        assert few_shot.exists(), f"missing few-shot file for {code}"
        raw = json.loads(few_shot.read_text(encoding="utf-8"))
        assert len(raw) >= 1
        for example in raw:
            en = [s for s in example["english"].split("/") if s.strip()]
            defs = [s for s in example["definition"].split("/") if s.strip()]
            assert len(en) == len(defs) >= 1
            assert "confidence" not in example
        keys = [
            compute_lexical_identity(e["traditional"], e["simplified"], e["pinyin"])
            for e in raw
        ]
        assert len(set(keys)) == len(keys)  # no duplicate few-shot entries
    # French set keeps its curated size (regression guard on the move).
    fr_raw = json.loads(
        (
            Path(prompt_module.__file__).parent
            / "assets"
            / LANGUAGES["fr"].few_shot
        ).read_text(encoding="utf-8")
    )
    assert len(fr_raw) >= 16


def test_prompt_states_label_abbreviation_rules():
    # Regression test for the 行 xing2 report: verbose calques such as
    # "(forme fermée)" / "(écriture littéraire)" instead of "lit.".
    system, _ = render_prompt(make_items(), "fr")
    assert '(bound form)' in system
    assert 'DROP' in system
    assert '"lit. "' in system or "'lit." in system or 'lit.' in system
    assert '(Tw [X])' in system
    assert 'KEEP it verbatim' in system or '"(Tw)"' in system
    for forbidden in ("forme fermée", "écriture littéraire", "prononcé en"):
        assert forbidden in system  # named in the FORBIDDEN list, not as usage
    assert "à Taïwan" in system  # named in the FORBIDDEN list, not as usage
    assert "old variant of" in system
    assert "forme ancienne de" in system
    # Regression test for the 3C/3D打印 report: whole definitions wrapped
    # in outer parentheses instead of bare dictionary style.
    assert "Never wrap the whole French definition" in system


def test_few_shot_demonstrates_label_rules():
    # The model must see at least one bound-form drop, one lit. mapping,
    # and one Tw mapping in the examples it is shown.
    from cfdict_next.generation.prompt import EXAMPLE_ITEMS, EXAMPLE_OUTPUTS

    defs_all = " / ".join(
        s["definition"] for out in EXAMPLE_OUTPUTS for s in out["senses"]
    )
    gloss_all = " / ".join(
        s["gloss"] for out in EXAMPLE_OUTPUTS for s in out["senses"]
    )
    assert "(bound form)" in gloss_all
    assert "(literary)" in gloss_all
    assert "(Taiwan pr." in gloss_all
    assert "(Tw) band-aid" in gloss_all  # OK绷: bare (Tw) preservation case
    assert "lit." in defs_all
    assert "(Tw [" in defs_all
    assert "(Tw) pansement adhésif" in defs_all  # kept verbatim, never expanded
    assert "old variant of" in gloss_all
    assert "forme ancienne de 帽[mao4]" in defs_all  # reference kept, not translated
    assert "de la casquette" not in defs_all
    # 3C: bare definitions, inner (CCC) kept, no outer wrap.
    assert "computers, communications, and consumer electronics" in gloss_all
    assert "ordinateurs, communications et électronique grand public" in defs_all
    assert "certification obligatoire chinoise (CCC)" in defs_all
    assert "(imprimante 3D)" not in defs_all
    assert "(impression en trois dimensions)" not in defs_all
    for forbidden in ("forme fermée", "écriture littéraire", "prononcé en", "(à Taïwan"):
        # "(à Taïwan" with paren: the label expansion. Bare "à Taïwan" in
        # running text is legitimate (cf. 小朋友 usage note) and not banned.
        assert forbidden not in defs_all


def test_every_language_template_exists_and_has_example_slot():
    from cfdict_next.generation import prompt as prompt_module
    from cfdict_next.languages import LANGUAGES

    from pathlib import Path

    for code, cfg in LANGUAGES.items():
        template = Path(prompt_module.__file__).parent / "assets" / cfg.prompt_template
        assert template.exists(), f"missing template for {code}"
        assert "{example_lines}" in template.read_text(encoding="utf-8")


def test_hsk3_prompt_renders_with_hsk3_voice():
    system, user = render_prompt(make_items(), "zh-CN-HSK03")
    assert "{example_lines}" not in system
    assert "HSK 3" in system
    assert "simplified Chinese only" in system
    assert user.startswith("Explain the meanings")
    assert '"China"' in user and '"Middle Kingdom"' in user


def test_hsk3_few_shot_loads_with_gloss_parity():
    from cfdict_next.generation.prompt import load_few_shot_for

    items, outputs = load_few_shot_for("zh-CN-HSK03")
    assert len(items) >= 3
    for item, output in zip(items, outputs):
        assert [s["gloss"] for s in output["senses"]] == list(item.glosses)
        assert all(s["definition"].strip() for s in output["senses"])


def test_french_render_is_unchanged_by_multilingual_support():
    # The fr registry values reproduce the pre-multilingual prompt exactly.
    system, user = render_prompt(make_items(), "fr")
    assert "lexicography" in system
    assert user.startswith("Translate the meanings")
    assert '[0] 中国 (中國, Zhong1 guo2) — senses:' in user


def test_unknown_language_fails_loudly():
    with pytest.raises(ValueError, match="xx-unknown"):
        render_prompt(make_items(), "xx-unknown")


# --- llm client ---


def test_generate_batch_maps_entries_to_sense_lists():
    def fake_post(endpoint, model, system, user, timeout_s):
        assert "chat/completions" in endpoint
        return chat_body(
            [
                {
                    "id": 1,
                    "word": "行",
                    "senses": [{"gloss": "to walk", "definition": "marcher"}],
                },
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays d'Asie"},
                        {"gloss": "Middle Kingdom", "definition": "Empire du Milieu"},
                    ],
                },
            ]
        )

    outcome = generate_batch(make_items(), make_config(), language="fr", post=fake_post)
    assert outcome.failed == []
    results = outcome.results
    assert [r.key for r in results] == ["中國|中国|Zhong1 guo2", "行|行|Xing2"]
    assert [(s.gloss, s.definition) for s in results[0].senses] == [
        ("China", "pays d'Asie"),
        ("Middle Kingdom", "Empire du Milieu"),
    ]
    assert len(results) == 2


def test_generate_batch_renders_hsk3_prompt():
    def fake_post(endpoint, model, system, user, timeout_s):
        assert "HSK 3" in system
        assert "Explain the meanings" in user
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "一个很大的国家"},
                        {"gloss": "Middle Kingdom", "definition": "中国以前的名字"},
                    ],
                },
                {
                    "id": 1,
                    "word": "行",
                    "senses": [{"gloss": "to walk", "definition": "用脚走路"}],
                },
            ]
        )

    outcome = generate_batch(
        make_items(), make_config(), language="zh-CN-HSK03", post=fake_post
    )
    assert outcome.failed == []
    assert [(s.gloss, s.definition) for s in outcome.results[0].senses] == [
        ("China", "一个很大的国家"),
        ("Middle Kingdom", "中国以前的名字"),
    ]


def test_generate_batch_rejects_unknown_language():
    with pytest.raises(ValueError, match="xx-unknown"):
        generate_batch(make_items(), make_config(), language="xx-unknown",
                       post=lambda *a: None)


def test_dropped_sense_fails_the_batch():
    def fake_post(*args):
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [{"gloss": "China", "definition": "pays"}],
                }
            ]
        )

    with pytest.raises(GenerationError, match="dropped sense.*Middle Kingdom"):
        generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)


def test_invented_sense_fails_the_batch():
    def fake_post(*args):
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays"},
                        {"gloss": "Middle Kingdom", "definition": "Empire"},
                        {"gloss": "Cathay", "definition": "Cathay"},
                    ],
                }
            ]
        )

    with pytest.raises(GenerationError, match="invented sense.*Cathay"):
        generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)


def test_extra_confidence_field_is_ignored():
    def fake_post(*args):
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays"},
                        {"gloss": "Middle Kingdom", "definition": "Empire"},
                    ],
                    "confidence": "confident",
                }
            ]
        )

    outcome = generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)
    assert outcome.failed == []
    (result,) = outcome.results
    assert [s.gloss for s in result.senses] == ["China", "Middle Kingdom"]


def test_missing_id_retries_then_raises():
    calls = []

    def fake_post(*args):
        calls.append(1)
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays"},
                        {"gloss": "Middle Kingdom", "definition": "Empire"},
                    ],
                }
            ]
        )

    outcome = generate_batch(make_items(), make_config(max_retries=2), language="fr", post=fake_post)
    assert [r.key for r in outcome.results] == ["中國|中国|Zhong1 guo2"]
    assert [i.key for i in outcome.failed] == ["行|行|Xing2"]
    assert "missing id 1" in outcome.causes["行|行|Xing2"]
    assert len(calls) == 1  # salvaged at once: no whole-batch retries burned


def test_word_mismatch_is_rejected():
    def fake_post(*args):
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "美国",
                    "senses": [{"gloss": "China", "definition": "pays"}],
                }
            ]
        )

    with pytest.raises(GenerationError, match="does not match"):
        generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)


def test_non_array_response_is_rejected():
    def fake_post(*args):
        return {"choices": [{"message": {"content": '{"id": 0}'}}]}

    with pytest.raises(GenerationError, match="JSON array"):
        generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)


def test_fenced_json_content_is_accepted():
    # Real LLMs wrap the array in ```json fences despite 'No markdown'.
    from cfdict_next.generation.llm import _parse_content

    payload = json.dumps(
        [{"id": 0, "word": "x", "senses": []}]
    )
    assert _parse_content(f"```json\n{payload}\n```")[0]["id"] == 0
    assert _parse_content(f"```\n{payload}\n```")[0]["word"] == "x"
    assert _parse_content(f"  ```json\n{payload}\n```  \n")[0]["id"] == 0
    assert _parse_content(payload)[0]["id"] == 0  # no fences: unchanged


def test_generate_batch_accepts_fenced_content():
    fenced = (
        "```json\n"
        + json.dumps(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays"},
                        {"gloss": "Middle Kingdom", "definition": "Empire"},
                    ],
                }
            ]
        )
        + "\n```"
    )

    def fake_post(*args):
        return {"choices": [{"message": {"content": fenced}}]}

    outcome = generate_batch(make_items()[:1], make_config(), language="fr", post=fake_post)
    assert outcome.failed == []
    (result,) = outcome.results
    assert [s.gloss for s in result.senses] == ["China", "Middle Kingdom"]


def test_partial_salvage_returns_good_and_defers_bad():
    # One bogus entry (dropped sense) beside a good one: exactly one
    # endpoint call, good entry returned, bad one deferred with its cause.
    calls = []

    def fake_post(*args):
        calls.append(1)
        return chat_body(
            [
                {
                    "id": 0,
                    "word": "中国",
                    "senses": [
                        {"gloss": "China", "definition": "pays"},
                        {"gloss": "Middle Kingdom", "definition": "Empire"},
                    ],
                },
                {
                    "id": 1,
                    "word": "行",
                    "senses": [],
                },
            ]
        )

    outcome = generate_batch(make_items(), make_config(), language="fr", post=fake_post)
    assert [r.key for r in outcome.results] == ["中國|中国|Zhong1 guo2"]
    assert [i.key for i in outcome.failed] == ["行|行|Xing2"]
    assert "non-empty array" in outcome.causes["行|行|Xing2"]
    assert len(calls) == 1


def test_envelope_failure_retries_whole_batch_then_raises():
    calls = []

    def fake_post(*args):
        calls.append(1)
        return {"choices": [{"message": {"content": '{"id": 0}'}}]}

    with pytest.raises(GenerationError, match="JSON array"):
        generate_batch(make_items(), make_config(max_retries=2), language="fr", post=fake_post)
    assert len(calls) == 3  # 1 initial + 2 retries


def test_single_transient_failure_recovers_on_retry():
    calls = []
    good = chat_body(
        [
            {
                "id": 0,
                "word": "中国",
                "senses": [
                    {"gloss": "China", "definition": "pays"},
                    {"gloss": "Middle Kingdom", "definition": "Empire"},
                ],
            }
        ]
    )

    def fake_post(*args):
        calls.append(1)
        if len(calls) == 1:
            return chat_body(
                [
                    {
                        "id": 0,
                        "word": "中国",
                        "senses": [{"gloss": "China", "definition": "pays"}],
                    }
                ]
            )
        return good

    outcome = generate_batch(
        make_items()[:1], make_config(max_retries=2), language="fr", post=fake_post
    )
    assert outcome.failed == []
    assert [r.key for r in outcome.results] == ["中國|中国|Zhong1 guo2"]
    assert len(calls) == 2


def test_empty_batch_is_rejected():
    with pytest.raises(GenerationError, match="empty batch"):
        generate_batch([], make_config(), language="fr", post=lambda *a: None)


def test_entry_without_glosses_is_rejected():
    bad = GenerationItem(key="K", traditional="T", simplified="S", pinyin="P", glosses=())
    with pytest.raises(GenerationError, match="no glosses"):
        generate_batch([bad], make_config(), language="fr", post=lambda *a: None)


# --- output ---


def provenance():
    return Provenance(cc_cedict_version="mdbg-test", llm_model="test-model",
                        prompt_version=PROMPT_VERSION)


def test_build_records_groups_single_mapping():
    from cfdict_next.generation.llm import GenerationResult

    results = [
        GenerationResult(
            key="中國|中国|Zhong1 guo2", traditional="中國", simplified="中国",
            pinyin="Zhong1 guo2",
            senses=(Sense("China", "pays"), Sense("Middle Kingdom", "Empire")),
        ),
        GenerationResult(
            key="行|行|Xing2", traditional="行", simplified="行",
            pinyin="Xing2", senses=(Sense("to walk", "marcher (?)"),),
        ),
    ]
    records = build_records(
        results, provenance(), generation_date="2025-01-01T00:00:00+00:00"
    )
    assert set(records) == {"中國|中国|Zhong1 guo2", "行|行|Xing2"}
    record = records["中國|中国|Zhong1 guo2"]
    assert [s["source_gloss"] for s in record["senses"]] == ["China", "Middle Kingdom"]
    assert record["cc_cedict_version"] == "mdbg-test"
    assert record["llm_model"] == "test-model"
    assert record["prompt_version"] == PROMPT_VERSION
    assert record["generation_date"] == "2025-01-01T00:00:00+00:00"
    assert "confidence" not in record


def test_merge_refuses_overwrites():
    with pytest.raises(ValueError, match="refusing to overwrite"):
        merge_records({"K": {"a": 1}}, {"K": {"a": 2}})
    merged = merge_records({"A": 1}, {"B": 2})
    assert merged == {"A": 1, "B": 2}


def test_write_round_trips_through_loader(tmp_path):
    from cfdict_next.generation.llm import GenerationResult

    results = [
        GenerationResult(
            key="中國|中国|Zhong1 guo2", traditional="中國", simplified="中国",
            pinyin="Zhong1 guo2", senses=(Sense("China", "pays"),),
        ),
    ]
    records = build_records(results, provenance(), generation_date="x")
    path = tmp_path / "llm_generated.json"
    write_llm_json(path, records)
    assert not path.with_suffix(".json.tmp").exists()  # no tmp left behind
    loaded = load_llm_json(path)
    assert list(loaded) == ["中國|中国|Zhong1 guo2"]
