# LLM generation — input specification (spec §5, §6)

The LLM generation process is **offline**. For each item in the missing scope
(`CC-CEDICT − base − human − LLM`, see `src/cxdict/scope.py`), the CEDICT entry is
processed **at the gloss/sense level**, not at the entry level.

Example (spec §5): the entry

    中國 中国 [Zhong1 guo2] /China/Middle Kingdom/

produces **one** generation input carrying both glosses (a separate
prompt runs per gloss at generation time):

```json
{
  "simplified": "中国",
  "traditional": "中國",
  "pinyin": "Zhong1 guo2",
  "glosses": ["China", "Middle Kingdom"]
}
```

## Input record fields

Generation still runs **per gloss** (one prompt per sense), but inputs
are grouped per lexical entry exactly like the outputs: one record per
entry, carrying the full gloss list. Input and output share the same
identity keys — glosses in, senses out.

Each generation input MUST provide exactly these fields:

| field        | role                                    | example                  |
|--------------|-----------------------------------------|--------------------------|
| `simplified` | Chinese simplified — **primary source** | 中国                     |
| `traditional`| Chinese traditional — primary source    | 中國                     |
| `pinyin`     | Pinyin with tone numbers — **primary source** | Zhong1 guo2          |
| `glosses`    | All CEDICT English glosses for the entry — **reference only** | ["China", "Middle Kingdom"] |

## The governing principle (spec §6)

```
Chinese simplified + Pinyin
            │
            │ primary source
            ▼
           LLM
            ▲
            │ reference/context
      English CEDICT gloss
```

The French output must be a **proper French dictionary definition of the
Chinese sense**, not a mechanical English → French translation of the gloss.
The English gloss is context for disambiguation (which sense is meant); the
simplified Chinese + pinyin carry the meaning to be defined.

Concretely, a prompt built from this spec MUST instruct the model to:

1. Read the meaning from the Chinese form and its pronunciation.
2. Consult the English gloss only to confirm which sense applies.
3. Write the definition as a French dictionary would (part of speech
   implied by phrasing, e.g. "pays d'Asie de l'Est" rather than "Chine").
4. NEVER emit a bare translation of the English gloss.

## Worked example

Input:

```json
{
  "simplified": "中国",
  "traditional": "中國",
  "pinyin": "Zhong1 guo2",
  "glosses": ["China", "Middle Kingdom"]
}
```

Generation runs one prompt per entry carrying its full gloss list, so
the French definitions for an entry's senses are produced together —
differentiated and consistent — rather than in isolated per-gloss calls
where the model could blend the senses.

Acceptable output sense: a French definition of China *as the historical
"Middle Kingdom" concept* (e.g. "nom historique de la Chine, l'« Empire du
Milieu »"), NOT the translation "Royaume du Milieu" standing alone without
dictionary framing — and never just "Middle Kingdom" translated word for word
without reference to the Chinese sense.

See `tests/fixtures/llm_example.json` for a complete input/output pair, and
`docs/llm_output_spec.md` for the output record format. Note that generation
sends one prompt per entry carrying its full gloss list, and the outputs for
one entry are grouped into a single record whose senses must cover all of
the entry's
glosses (gloss parity — see the output spec).

## Other languages

The worked example above is the French instantiation (templates in
`dictionaries/fr/assets/`; the HSK3 templates live in
`dictionaries/zh-CN-HSK03/assets/`). Every language follows the same
contract — Chinese + pinyin as the primary source, English glosses as
disambiguation anchors, one `definition` per gloss — differing only in
the target voice (French dictionary style vs. HSK3-level Chinese).
