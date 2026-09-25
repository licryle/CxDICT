# Maintenance checklist

## Periodic

- [ ] CC-CEDICT freshness — is the snapshot in `data/` older than the
      release cadence demands? If yes, follow `update_procedures.md`.
- [ ] LLM dataset size — `python -c` on each
      `data/<lang>/llm_generated.json` record count; missing scope should
      shrink as generation runs.
- [ ] Dependency health — `nix flake update` dry-run; `pip` audit of
      `jsonschema`/`pyyaml` for advisories.

## On demand

- [ ] CFDICT upstream fix → `data/fr/cfdict.u8` → `cleanup --language fr`
      → review diff → `validate --language fr` → commit.
- [ ] New prompt version → template file under `assets/<code>/` + version
      bump for that language → trial generations → suite green → commit.
- [ ] New model → `.env` change (local only) → trial batch → judge
      definition quality (French / HSK3) before any bulk run.

## Per release (CI does it, human confirms)

- [ ] Actions run green (test → validate → assemble → validate → scope).
- [ ] Release notes figures sane (missing scope moves only as expected).
- [ ] Both `<slug>-next-*.u8` assets attached (currently `output/fr/`).

## Troubleshooting

| symptom | cause → fix |
|---|---|
| `validate` reports overlap | lower-priority datasets stale vs base/human → run `scripts/cleanup.py --language <code>`, review diff, commit |
| `validate` reports gloss mismatch | CC-CEDICT drifted under existing LLM records → regenerate affected entries or pin the older snapshot |
| `validate` reports hanzi/pinyin | human entry disagrees with CC-CEDICT pairing/reading → fix `data/<lang>/human.u8` |
| `assemble` refuses overlap | same as overlap above — assembly never overrides; clean first |
| `generate` `GenerationError: missing id` | model dropped an entry — retry; persistent drops mean the batch is too large or the model too small |
| `nix develop` broken | `nix flake check`; fallback is venv + `pip install -e .` (sets `PYTHONPATH` equivalent) |
| CI red on `gh release` | check `contents: write` permission and tag collision (two pushes within one second) |
