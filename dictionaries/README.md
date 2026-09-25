# Source data

This directory holds the source datasets, one subdirectory per target
language (`fr`, `zh-CN-HSK03`); CC-CEDICT is the shared Chinese lexical scope for every language. Provenance (URL, date, checksum) is recorded
here for every file, per specification §3, §12 and §16 (releases must
be traceable to exact source versions).

## CC-CEDICT (lexical scope)

- File: `cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz` (stored verbatim as published)
- Source URL: https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
- Downloaded (UTC): 2025-09-12
- SHA-256: `b8c062da61ed1709c52a2a26370f18dfc0fcd4d4c487a9628fa73eb336e341e4`
- Size: 125,076 lines (uncompressed)
- Format: CEDICT — `traditional simplified [pinyin] /gloss1/gloss2/.../`,
  `#` lines are metadata/comments.
- Quirk: this snapshot uses CRLF (`\r\n`) line endings on every line;
  parsers must normalize before matching (verified: all 125,046 entry
  lines are canonical after stripping `\r`).
- Note: MDBG serves a daily snapshot without an explicit version identifier;
  the SHA-256 above is the release-pinning reference for this snapshot.

## CFDICT (authoritative French definitions, `fr` only)

- File: `fr/data/cfdict.u8`
- Source URL: https://chine.in/assets/cfdict/cfdict.u8 (provided by maintainer)
- Downloaded (UTC): 2025-09-12
- SHA-256: `124d87f0fc2aed305e42ec3794584fa62bf00df9ed0aac45b950aba518795e75`
- Size: 56,326 lines (3,522,011 bytes)
- Format: CEDICT — `traditional simplified [pinyin] /définition1/définition2/.../`,
  `#` lines are metadata/comments.
- Quirk: CRLF (`\r\n`) line endings on every line (like the CC-CEDICT
  snapshot); parsers normalize before matching.
- This file is the forked authoritative source (spec §2); future updates
  arrive via pull requests against it.

## Human curation (free-form target language)

- Files: `fr/data/human.u8`, `zh-CN-HSK03/data/human.u8` (empty until curated)
- Format: CEDICT — `traditional simplified [pinyin] /définition1/définition2/.../`,
  `#` lines are metadata/comments.
- Precedence: CFDICT > human.u8 > llm_generated.json (spec §9). Entries
  overlapping CFDICT are removed by `scripts/cleanup.py`.
- Validation: no gloss-count check; when CC-CEDICT knows the
  (traditional, simplified) pair, the pinyin must be one of its observed
  readings, and mixed hanzi pairs fail (spec §14).

## HSK3 (`zh-CN-HSK03`): no authoritative base

- There is no upstream base dictionary: generation starts from human
  curation + LLM output over CC-CEDICT scope.
  `zh-CN-HSK03/data/human.u8` (empty) and
  `zh-CN-HSK03/data/llm_generated.json` (`{}`) are the skeletons;
  definitions must stay understandable to an HSK3 learner, using mostly
  HSK3 vocabulary.

## LLM-generated definitions (unified per-language datasets)

- Files: `fr/data/llm_generated.json` (77,077 records merged from the former
  `confident.json` + `review.json`; per-record `confidence` field dropped
  2026-09-18 — the model is no longer asked to rate itself).
- Format: JSON object mapping `traditional|simplified|pinyin` identity →
  record (schema `src/cxdict/schemas/llm_entry.json`); one sense per CC-CEDICT gloss.
- Precedence: lowest. Entries overlapping CFDICT or human.u8 are removed
  by `scripts/cleanup.py`.
- Validation: every record must cover exactly its CC-CEDICT gloss set and
  reference an identity inside CC-CEDICT scope (spec §14).
