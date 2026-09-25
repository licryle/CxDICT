"""Per-language configuration, loaded from ``dict.toml`` files (CXDict boundary).

Everything that varies per target language lives OUTSIDE this package, in
``dictionaries/<code>/`` units: ``dict.toml`` at the unit root plus
``data/`` and ``assets/`` subdirectories. Prompt template and few-shot
paths inside the TOML are relative to the TOML file's directory, so units
stay relocatable. The engine itself ships zero language content: adding
a language means adding a directory, never editing engine code.

Resolution is a plain CWD convention — ``./dictionaries`` — so checkouts
and child repos work with no extra flags.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# CC-CEDICT is the shared Chinese lexical scope for every language —
# a dict.toml-less directory under ``dictionaries/``.
CC_CEDICT_REL = Path("dictionaries/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz")

#: Language units directory (CWD-relative).
DICTIONARIES_DIR = Path("dictionaries")

#: Fields every dict.toml must define (besides the optional base pair).
_REQUIRED_FIELDS = (
    "code",
    "base_label",
    "prompt_template",
    "few_shot",
    "prompt_version",
    "prompt_user_intro",
    "target_language_name",
    "output_slug",
    "release_name",
    "description",
)


@dataclass(frozen=True)
class LanguageConfig:
    """Everything that varies per target language, loaded from dict.toml."""

    code: str  # directory key, mirroring dictionaries/<code>/ and output/<code>/
    base_filename: str | None  # authoritative base filename in dictionaries/<code>/data/ (None = no base)
    base_label: str  # human label rendered in scope info / section headers
    base_url: str | None  # provenance URL for the base (None when there is no upstream)
    prompt_template: Path  # absolute path of the versioned prompt template
    few_shot: Path  # absolute path of the curated few-shot examples
    prompt_version: str  # stamped on every generated record
    prompt_user_intro: str  # user-message prefix for generation batches
    target_language_name: str  # used when rendering prompts ("French", ...)
    output_slug: str  # output/<code>/<slug>-next-{human,full}.u8
    release_name: str  # short display name used in release assets (no slashes)
    description: str  # one-line description of the target dictionary
    config_dir: Path = field(compare=False)  # directory holding dict.toml


def _lang_toml_path(code: str) -> Path:
    return DICTIONARIES_DIR / code / "dict.toml"


def get_language(code: str) -> LanguageConfig:
    """Load and validate one language definition; fail loud on any problem."""
    if not code or "/" in code or "\\" in code or code in (".", ".."):
        raise ValueError(f"invalid language code {code!r}")
    toml_path = _lang_toml_path(code)
    try:
        with open(toml_path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ValueError(
            f"unknown language {code!r} (no {toml_path}; "
            "run from a tree holding dictionaries/<code>/dict.toml)"
        ) from None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{toml_path}: cannot load language definition: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{toml_path}: top level must be a TOML table")
    unknown = sorted(set(raw) - set(_REQUIRED_FIELDS) - {"base_filename", "base_url"})
    if unknown:
        raise ValueError(f"{toml_path}: unknown field(s): {', '.join(unknown)}")
    missing = [name for name in _REQUIRED_FIELDS if name not in raw]
    if missing:
        raise ValueError(f"{toml_path}: missing field(s): {', '.join(missing)}")
    for name in (*_REQUIRED_FIELDS, "base_filename", "base_url"):
        value = raw.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{toml_path}: {name!r} must be a string")
    if raw["code"] != code:
        raise ValueError(
            f"{toml_path}: code is {raw['code']!r} but {code!r} was requested"
        )
    release_name = raw["release_name"]
    if not release_name.strip() or "/" in release_name or "\\" in release_name:
        raise ValueError(
            f"{toml_path}: 'release_name' must be a bare filename-safe name"
        )
    config_dir = toml_path.parent.absolute()
    template = config_dir / raw["prompt_template"]
    few_shot = config_dir / raw["few_shot"]
    for label, path in (("prompt_template", template), ("few_shot", few_shot)):
        if not path.is_file():
            raise ValueError(f"{toml_path}: {label} not found: {path}")
    return LanguageConfig(
        code=raw["code"],
        base_filename=raw.get("base_filename"),
        base_url=raw.get("base_url"),
        base_label=raw["base_label"],
        prompt_template=template,
        few_shot=few_shot,
        prompt_version=raw["prompt_version"],
        prompt_user_intro=raw["prompt_user_intro"],
        target_language_name=raw["target_language_name"],
        output_slug=raw["output_slug"],
        release_name=release_name,
        description=raw["description"],
        config_dir=config_dir,
    )


@dataclass(frozen=True)
class ResolvedPaths:
    """Concrete file locations for one language run."""

    base: Path | None
    human: Path
    llm_generated: Path
    cc_cedict: Path
    out_human: Path
    out_full: Path
    scope_out: Path


def resolve_paths(
    code: str,
    repo_root: str | Path = ".",
    *,
    base: str | Path | None = None,
    human: str | Path | None = None,
    llm_generated: str | Path | None = None,
    cc_cedict: str | Path | None = None,
    out_human: str | Path | None = None,
    out_full: str | Path | None = None,
    scope_out: str | Path | None = None,
) -> ResolvedPaths:
    """Resolve default ``dictionaries/<lang>/data/`` + ``output/<lang>/`` paths.

    Explicit arguments win over language defaults, so every CLI can accept
    ``--base/--human/...`` overrides while ``--language`` supplies the rest.
    ``repo_root`` anchors all relative defaults (tests pass ``tmp_path``).
    The language definition itself always comes from ``./dictionaries`` (CWD
    convention) — pass an absolute ``repo_root`` and matching overrides
    when driving another tree.
    Languages without an authoritative base (``base_filename is None``)
    resolve ``base`` to None unless an explicit ``base=`` override is given;
    downstream stages treat None as "no base identities" (empty set).
    Empty-string overrides count as not given.
    """
    cfg = get_language(code)
    root = Path(repo_root)
    data_dir = root / "dictionaries" / cfg.code / "data"
    out_dir = root / "output" / cfg.code
    if base:
        resolved_base: Path | None = Path(base)
    elif cfg.base_filename is None:
        resolved_base = None
    else:
        resolved_base = data_dir / cfg.base_filename
    return ResolvedPaths(
        base=resolved_base,
        human=Path(human) if human else data_dir / "human.u8",
        llm_generated=(
            Path(llm_generated) if llm_generated else data_dir / "llm_generated.json"
        ),
        cc_cedict=Path(cc_cedict) if cc_cedict else root / CC_CEDICT_REL,
        out_human=(
            Path(out_human)
            if out_human
            else out_dir / f"{cfg.output_slug}-next-human.u8"
        ),
        out_full=(
            Path(out_full)
            if out_full
            else out_dir / f"{cfg.output_slug}-next-full.u8"
        ),
        scope_out=Path(scope_out) if scope_out else out_dir / "scope.md",
    )
