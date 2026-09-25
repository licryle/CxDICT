# LLM generation — output specification (spec §4, §8)

## File layout

One JSON file mapping **lexical identity → record** (spec §15):

- `llm_generated.json` — unified LLM output, assembled into the full
  dictionary (§10.2).

The identity key MUST equal the identity computed from the record's own
`traditional`/`simplified`/`pinyin` fields; `src/cfdict_next/parser/json.py` rejects
any mismatch instead of guessing (spec §14).

Human curation lives separately in `data/<lang>/human.u8` (raw .u8,
free-form target language). The model is never asked to rate its own
confidence.

## Record layout: one record per entry, one sense per gloss

Generation happens per gloss (see `docs/llm_input_spec.md`), but records
are grouped per lexical entry: each record carries a `senses` list with
one `{source_gloss, definition}` pair per CEDICT gloss. There is
no separate record per gloss — the identity key alone cannot distinguish
glosses, so per-gloss records would collide and could silently overwrite
each other.

## Record fields (provenance, spec §8)

Every record MUST carry all of these fields:

| field               | meaning                                              |
|---------------------|------------------------------------------------------|
| `traditional`       | Traditional Chinese form                             |
| `simplified`        | Simplified Chinese form                              |
| `pinyin`            | Pinyin with tone numbers                             |
| `senses`            | List of `{source_gloss, definition}` — one sense per CEDICT gloss (see gloss parity below) |
| `cc_cedict_version` | CC-CEDICT snapshot the gloss came from (e.g. SHA-256 + date in `data/README.md`) |
| `llm_model`         | LLM model **and version** used                       |
| `prompt_version`    | Prompt template version used                         |
| `generation_date`   | ISO 8601 timestamp of generation                     |

The formal schema is `schemas/llm_entry.json` — the single normative
source enforced by `src/cfdict_next/parser/json.py` (spec §14). The file
schema `schemas/llm_generated_schema.json` is a thin `$ref` wrapper
around it.

## Gloss parity — accept/reject criterion

Each target dictionary must carry the **same number of glosses per
entry as the English source**: the set of `source_gloss` values in a
record must **exactly equal** the CC-CEDICT gloss set for that entry.
A record that drops a gloss, or invents one absent from CC-CEDICT, is
**rejected** — never silently repaired (spec §14).

Enforced by `src/cfdict_next/parser/json.py::assert_gloss_coverage`, which names the
missing and/or extra glosses. The loader itself cannot run this check
(it sees only the JSON file, not CC-CEDICT); Phase 9 wires the two
datasets together using this single shared implementation.

## Example

See `tests/fixtures/llm_example.json`: example records with their
generation inputs.
