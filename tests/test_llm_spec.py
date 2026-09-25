"""Tests for the LLM generation interface spec (plan Step 4.5, spec §5, §6, §8, §15).

These tests pin the contract between docs, example, schema and loader:
the example in tests/fixtures/llm_example.json must satisfy the loader's
validation, the example's senses must exactly cover its inputs' glosses
(gloss parity), and the schema must require exactly the provenance fields
the loader enforces.
"""

import json
from importlib import resources
from pathlib import Path

from cxdict.parser.json import REQUIRED_FIELDS, assert_gloss_coverage, validate_record

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "tests" / "fixtures" / "llm_example.json"

# Packaged schema (same file the loader enforces at runtime).
SCHEMA = (
    resources.files("cxdict") / "schemas" / "llm_entry.json"
)


def _example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_inputs_carry_the_four_spec_fields():
    # Spec §6: simplified, traditional, pinyin (primary) + glosses
    # (reference). One record per entry, mirroring the outputs.
    for key, inp in _example()["inputs"].items():
        assert set(inp) == {"simplified", "traditional", "pinyin", "glosses"}
        for f in ("simplified", "traditional", "pinyin"):
            assert isinstance(inp[f], str) and inp[f].strip()
        assert isinstance(inp["glosses"], list) and len(inp["glosses"]) >= 1
        assert all(isinstance(g, str) and g.strip() for g in inp["glosses"])


def test_example_outputs_validate_against_loader():
    # The documented example must pass the same validation as real data.
    outputs = _example()["outputs"]
    for key, record in outputs.items():
        assert validate_record(key, record) == key


def test_example_has_no_confidence_field():
    for record in _example()["outputs"].values():
        assert "confidence" not in record


def test_example_senses_cover_exactly_the_input_glosses():
    # Gloss parity at the example level: input and output share the same
    # identity keys, and each output's senses cover exactly the input's
    # glosses — the accept/reject criterion, demonstrated.
    example = _example()
    assert set(example["outputs"]) == set(example["inputs"])
    for key, record in example["outputs"].items():
        assert_gloss_coverage(record, set(example["inputs"][key]["glosses"]))


def test_schema_requires_exactly_the_loader_fields():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) == set(REQUIRED_FIELDS)
    assert "confidence" not in schema["required"]
    assert "confidence" not in schema.get("properties", {})


def test_generated_file_schema_shares_the_record_shape():
    # llm_generated_schema.json must not duplicate the record shape: it
    # references llm_entry.json.
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    entry_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry = Registry().with_resource(
        "llm_entry.json", Resource.from_contents(entry_schema, default_specification=DRAFT7)
    )
    generated_schema = json.loads(
        (
            resources.files("cxdict")
            / "schemas"
            / "llm_generated_schema.json"
        ).read_text(encoding="utf-8")
    )
    outputs = _example()["outputs"]
    record = next(iter(outputs.values()))
    validator = jsonschema.Draft7Validator(generated_schema, registry=registry)
    validator.validate({"k": record})  # no raise
