# Update procedures

## CC-CEDICT snapshot

1. Download the current snapshot to
   `data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz` (same URL as recorded
   in `data/README.md`).
2. Record the download date and new SHA-256 in `data/README.md`.
3. Run `python scripts/validate.py --language fr` (and
   `--language zh-CN-HSK03`) — gloss changes surface as coverage
   mismatches against existing LLM records; regenerate or correct the
   affected records.
4. Run the pipeline through `scope_info.py` and commit data + README.

The missing scope recomputes automatically from the new snapshot, so the
next `generate` run picks up exactly the new entries.

## CFDICT fork (`data/fr/cxdict.u8`)

1. Pull the upstream fix into `data/fr/cxdict.u8` (source URL in
   `data/README.md`).
2. Run `python scripts/cleanup.py --language fr` (no `--dry-run`) —
   entries now covered by CFDICT leave `human.u8` and the LLM dataset.
   Review the `git diff`, then commit.
3. Run validation + assembly; the release notes will show the shifted
   coverage.

## LLM data and prompt versions

- New records always carry `llm_model`, `prompt_version`,
  `cc_cedict_version`, and `generation_date` (spec §8, §16) — stamped by
  the orchestrator, never hand-written.
- A new prompt template means a new file under `assets/<code>/` (e.g.
  `fr/generate_fr_vN.txt`), a bumped prompt version for that language in
  `assets/<code>/dict.toml`, and re-validation of anything it produced.
  Never rewrite history: old records keep their original prompt version.
- Few-shot examples live in `assets/<code>/` and are machine-checked by
  the suite — editing them runs the same tests as code.

## Release cycle and versioning

Push to `main` → CI tests, validates, assembles, and publishes a
timestamp-tagged release with both dictionaries + scope notes. Source
versions are content hashes (see `scope_info.py`), so any release is
reproducible from its recorded inputs plus the tagged tooling. The Nix
flake pins the toolchain; no system Python is ever involved.
