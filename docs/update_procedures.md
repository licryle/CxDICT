# Update procedures

## CC-CEDICT snapshot

1. Run `python scripts/fetch_cc_cedict.py [--dry-run]` — downloads the
   current MDBG snapshot (URL in `dictionaries/README.md`) and, when its
   content changed, stores it decompressed as
   `dictionaries/cc-cedict/YYYY-MM-DD.u8` and logs it in `snapshots.toml`.
   The pipeline itself never touches the network; it only reads committed
   files. No README edit is needed for the snapshot itself — the manifest
   is the log.
2. Run `python scripts/scope_sync.py` (dry run) and review the prune
   queue: LLM records whose pinyin or gloss set no longer matches the
   superset's canonical rows, plus HUMAN warnings (warn-only, never
   deleted). Nothing to prune is the common case — the superset keeps
   retired content valid. If pruning is needed, run with `--apply`
   (`--force` is required past 3% of a file) and commit the prune on its
   own so the deletion is reviewable.
3. Run `python scripts/validate.py --language <code>` — superset scope,
   fail loudly. `... --scope latest` is advisory (warnings only) and
   shows what the newest snapshot alone would flag, including
   base-scope divergences of the authoritative base.
4. Run `python scripts/pipeline.py --language <code>` (the missing scope
   picks up exactly the entries the datasets still lack, retired pairs
   included) and refresh the notes with
   `python scripts/scope_info.py --language <code>`; review the git diff,
   then commit data + manifest. The release publishes three assets —
   Human, SuperFull, LatestFull (see `docs/workflow.md`).

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
timestamp-tagged release with all three dictionaries + scope notes. Source
versions are content hashes (see `scope_info.py`), so any release is
reproducible from its recorded inputs plus the tagged tooling. The Nix
flake pins the toolchain; no system Python is ever involved.
