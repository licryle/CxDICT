# Release workflow (spec §13)

## Triggers

The `Assemble and release` workflow runs on every push to `main` that
touches release-relevant inputs, and on manual dispatch:

- `data/fr/**`, `data/zh-CN-HSK03/**` (per-language sources)
- `data/cc-cedict/**` (scope changes)
- `src/**`, `scripts/**`, `flake.nix` (tooling changes)
- the workflow file itself

## Pipeline order

1. **Test suite** (`test` job) — the full pytest suite must pass first.
2. **Validate inputs** — all §14 data relationships are gated before
   anything is produced. A failure names the violated check.
3. **Assemble** — `scripts/assemble.py --language fr` writes
   `output/fr/cfdict-next-human.u8` and `output/fr/cfdict-next-full.u8`
   (gitignored build artifacts, never committed).
4. **Validate outputs** — assembled files are checked against the inputs
   (exact identity sets, no duplicate lines).
5. **Scope information** — `scripts/scope_info.py` renders the release
   notes with content-hashed source versions (§12, §16).
6. **Publish** — a timestamp-tagged GitHub release with both `.u8` files
   as assets and the scope information as its notes body.

## Deliberately not automated: cleanup

Overlaps (a higher-priority entry lingering in a lower-priority dataset)
**fail** the workflow instead of being auto-fixed. Run
`scripts/cleanup.py --language fr` locally, review the diff, and commit
it — dataset deletions deserve a human-readable commit, not a silent
workflow push. The validation output tells you exactly which identities
overlap.

## Languages

Every script takes a required `--language` (`fr`, `zh-CN-HSK03` — no
default). CI builds French; the HSK3 dictionary runs the same commands
with `--language zh-CN-HSK03` against `data/zh-CN-HSK03/` (which has no
authoritative base: generation starts from human curation + LLM output).

## Cutting a release manually

Push a source-data change to `main`, or use *Run workflow* (workflow
dispatch) on `main` to re-release unchanged sources (e.g. after a
tooling-only fix).

## Permissions

The workflow needs `contents: write` to create releases and upload
assets. No other permissions are granted.

## Local verification (no `act`)

`act` needs a Docker daemon, which the dev container does not provide —
so the workflow YAML itself is checked in instead:

- `tests/test_workflow.py` asserts triggers, job ordering, permissions,
  and that every third-party action pins a major tag or SHA.
- The exact pipeline commands are executed end to end as subprocesses
  on fixture data (validate → assemble → validate → scope).
- Pinned action tags are verified to exist via the GitHub API before
  any workflow change is sanctioned.

The remaining untested surface — the runner environment, the Nix
installer action's behavior, and `gh release create` — is exercised on
the first real CI run; keep an eye on it.
