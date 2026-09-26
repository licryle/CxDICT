# Update procedures

## CC-CEDICT snapshot

1. Run `python scripts/fetch_cc_cedict.py [--dry-run]` — downloads the
   current MDBG snapshot (URL in `dictionaries/README.md`) and, when its
   content changed, stores it decompressed as
   `dictionaries/cc-cedict/YYYY-MM-DD.u8`, logs it in `snapshots.toml`,
   and prints a pair-level change summary (new / retired / changed pairs).
   The pipeline itself never touches the network; it only reads committed
   files. No README edit is needed for the snapshot itself — the manifest
   is the log.
2. Run `python scripts/validate.py --language fr` (and
   `--language zh-CN-HSK03`) — records whose pinyin or gloss set no longer
   matches fail the coverage checks; regenerate or correct the affected
   records (rule-3 pruning of the LLM datasets lands with scope_sync).
3. Run `python scripts/pipeline.py --language <code>` (the missing scope
   picks up exactly the entries the datasets still lack) and refresh the
   notes with `python scripts/scope_info.py --language <code>`; review the
   git diff, then commit data + manifest.

## CFDICT fork (`dictionaries/fr/data/cfdict.u8`)

1. Pull the upstream fix into `dictionaries/fr/data/cfdict.u8` (source
   URL in `dictionaries/README.md`).
2. Run `python scripts/cleanup.py --language fr` (no `--dry-run`) —
   entries now covered by CFDICT leave `human.u8` and the LLM dataset.
   Review the `git diff`, then commit.
3. Run validation + assembly; the release notes will show the shifted
   coverage.

## LLM data and prompt versions

- New records always carry `llm_model`, `prompt_version`,
  `cc_cedict_version`, and `generation_date` (spec §8, §16) — stamped by
  the orchestrator, never hand-written.
- A new prompt template means a new file under
  `dictionaries/<code>/assets/` (e.g. `fr/assets/generate_fr_vN.txt`), a
  bumped prompt version for that language in
  `dictionaries/<code>/dict.toml`, and re-validation of anything it
  produced. Never rewrite history: old records keep their original
  prompt version.
- Few-shot examples live in `dictionaries/<code>/assets/` and are
  machine-checked by the suite — editing them runs the same tests as code.

## Release cycle and versioning

Push to `main` → CI tests, validates, assembles, and publishes a
timestamp-tagged release with both dictionaries + scope notes. Source
versions are content hashes (see `scope_info.py`), so any release is
reproducible from its recorded inputs plus the tagged tooling. The Nix
flake pins the toolchain; no system Python is ever involved.
