# Release workflow (spec §13)

## Triggers

The `Assemble and release` workflow runs on every push to `main` that
touches release-relevant inputs, and on manual dispatch:

- `dictionaries/**` (language units — new languages need no workflow
  edits, they are discovered from `dictionaries/`)
- `src/**`, `scripts/**`, `flake.nix` (tooling changes)
- the workflow file itself

## Pipeline order

1. **Test suite** (`test` job) — the full pytest suite must pass first.
2. **Detect** (`changes` job) — map changed files to languages: a path
   under `dictionaries/<code>/` selects that language when the directory
   owns a `dict.toml`; any other path under `dictionaries/` (today: the
   shared `dictionaries/cc-cedict/` snapshot) selects every language, so
   scope updates can never merge silently. Paths outside `dictionaries/`
   (engine, tooling) cut no release — they still run the test suite;
   re-release via the button. Manual dispatch with `language: all` (the
   default) selects everything discovered under `dictionaries/`.
3. **Release matrix** (one job per detected language) — validate inputs
   (all §14 relationships gated before anything is produced; a failure
   names the violated check), assemble both dictionaries (gitignored
   build artifacts, never committed), validate outputs, render scope
   notes (§12, §16), publish. Languages release independently
   (`fail-fast: false`).

## Naming scheme

Tags are `CxDICT-<Name>-YYYYMMDD` (UTC, `<Name>` is the language's
`release_name` from `dict.toml`); assets are
`CxDICT-<Name>-YYYYMMDD-{Human,Full}.u8`
(e.g. `CxDICT-French-20260925-Human.u8`). Release titles match the tag
with the scope notes as body. A same-day re-run refreshes the day's
release in place (`upload --clobber` + notes update). Output paths stay
`output/<code>/` internally; only the published asset names carry the
scheme. Keep `release_name` short, ASCII, no spaces: it lands in tags,
asset names, and URLs verbatim.

## Latest pointer (`latest-<code>`)

Next to each dated release, one rolling release object per language is
refreshed in place every run — tag `latest-<code>` (e.g. `latest-fr`),
titled `CxDICT <Name> (latest)` — holding both stably-named assets
(`CxDICT-<Name>-Human.u8` and `CxDICT-<Name>-Full.u8`, no date). This is
our own per-language `:latest`, Docker-style: GitHub's own "Latest"
badge is repo-wide and cannot mark one release per language, so these
pointers are the stable links:

```
gh release download latest-fr --pattern '*-Full.u8'
https://github.com/<owner>/<repo>/releases/download/latest-fr/CxDICT-French-Full.u8
```

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
with `--language zh-CN-HSK03` against `dictionaries/zh-CN-HSK03/` (which
has no authoritative base: generation starts from human curation + LLM
output).

## Library releases (engine)

Dictionary releases above ship `.u8` files. Separately, `publish.yml`
ships the engine itself as a Python library: push a tag `vX.Y.Z`
(matching `version` in `pyproject.toml` — anything else fails fast) and
CI builds the wheel+sdist, smoke-tests a fresh install (including the
packaged schema file), and attaches both to the GitHub release. No PyPI
involved; children pin a version with a release-asset URL:

```
pip install https://github.com/<owner>/<repo>/releases/download/v0.1.0/<wheel>
```

Keep `version` in `pyproject.toml`, the tag, and the release notes in
agreement: bump, commit, tag, push.

## Cutting a release manually

Push a source-data change to `main`, or use *Run workflow* (workflow
dispatch) on `main` to re-release unchanged sources (e.g. after a
tooling-only fix). The dispatch takes an optional `language` input:
a code for one language, or `all` (the default) for everything under
`dictionaries/`.

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
