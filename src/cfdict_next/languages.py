"""Per-language configuration registry (multilingual steps 1+2).

Centralizes everything that varies per target language so the engine
(identity, parser, scope, cleanup, validation, assembly, orchestrator)
stays language-agnostic and consumes a :class:`LanguageConfig`.

P0 scope: additive only. Nothing else imports this module yet; later
phases (CLI defaults, prompt assets, headers, scope labels) will resolve
through :func:`get_language` / :func:`resolve_paths` instead of hardcoded
French paths and names.

Languages:
- ``fr`` — French definitions (current pipeline, backward compatible).
- ``zh-CN-HSK03`` — HSK3-level Chinese definitions: LLM-generated
  definitions that an HSK3 learner should understand, focused on using
  mostly HSK3 vocabulary. There is no authoritative upstream base, so
  ``base_filename``/``base_url`` are None and the pipeline runs
  human + LLM with the same precedence rules (base contributes nothing).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# CC-CEDICT is the shared Chinese lexical scope for every language —
# it lives outside any ``data/<lang>/`` directory.
CC_CEDICT_REL = Path("data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz")


@dataclass(frozen=True)
class LanguageConfig:
    """Everything that varies per target language."""

    code: str  # directory key: "fr", "zh-CN-HSK03" (data/<code>/, output/<code>/)
    base_filename: str | None  # authoritative base filename in data/<code>/ (None = no base)
    base_label: str  # human label rendered in scope info / section headers
    base_url: str | None  # provenance URL for the base (None when there is no upstream)
    prompt_template: str  # asset path relative to generation/assets/
    few_shot: str  # asset path relative to generation/assets/
    prompt_version: str  # stamped on every generated record
    definition_field: str  # sense-dict key holding the generated definition
    target_language_name: str  # used when rendering prompts ("French", ...)
    output_slug: str  # output/<code>/<slug>-next-{human,full}.u8
    description: str  # one-line description of the target dictionary


LANGUAGES: dict[str, LanguageConfig] = {
    "fr": LanguageConfig(
        code="fr",
        base_filename="cfdict.u8",
        base_label="CFDICT",
        base_url="https://chine.in/mandarin/dictionnaire/CFDICT/",
        prompt_template="fr/generate_fr_v5.txt",
        few_shot="fr/few_shot_examples.json",
        prompt_version="v5",
        definition_field="french_definition",
        target_language_name="French",
        output_slug="cfdict",
        description="French definitions (CFDICT authoritative base + LLM coverage).",
    ),
    "zh-CN-HSK03": LanguageConfig(
        code="zh-CN-HSK03",
        base_filename=None,
        base_label="HSK3 base",
        base_url=None,
        prompt_template="zh-CN-HSK03/generate_hsk3_v1.txt",
        few_shot="zh-CN-HSK03/few_shot_examples.json",
        prompt_version="v1",
        definition_field="hsk3_definition",
        target_language_name="HSK3-level Chinese",
        output_slug="hsk3",
        description=(
            "HSK3-level definitions, LLM generated, that an HSK3 learner should understand, "
            "hence focused on using mostly HSK3 vocabulary."
        ),
    ),
}

#: Backward-compatible default: the current pipeline behaves as ``fr``
#: unless ``--language`` says otherwise (P4 wires this into the CLIs).
DEFAULT_LANGUAGE = "fr"


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


def get_language(code: str) -> LanguageConfig:
    """Return the config for ``code``; raise ValueError listing available codes."""
    try:
        return LANGUAGES[code]
    except KeyError:
        available = ", ".join(sorted(LANGUAGES))
        raise ValueError(f"unknown language {code!r} (available: {available})") from None


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
    """Resolve default ``data/<lang>/`` + ``output/<lang>/`` paths with overrides.

    Explicit arguments win over language defaults, so every CLI can accept
    ``--base/--human/...`` overrides while ``--language`` supplies the rest.
    ``repo_root`` anchors all relative defaults (tests pass ``tmp_path``).
    Languages without an authoritative base (``base_filename is None``)
    resolve ``base`` to None unless an explicit ``base=`` override is given;
    downstream stages treat None as "no base identities" (empty set).
    """
    cfg = get_language(code)
    root = Path(repo_root)
    data_dir = root / "data" / cfg.code
    out_dir = root / "output" / cfg.code
    if base is not None:
        resolved_base: Path | None = Path(base)
    elif cfg.base_filename is None:
        resolved_base = None
    else:
        resolved_base = data_dir / cfg.base_filename
    return ResolvedPaths(
        base=resolved_base,
        human=Path(human) if human is not None else data_dir / "human.u8",
        llm_generated=(
            Path(llm_generated) if llm_generated is not None else data_dir / "llm_generated.json"
        ),
        cc_cedict=Path(cc_cedict) if cc_cedict is not None else root / CC_CEDICT_REL,
        out_human=(
            Path(out_human)
            if out_human is not None
            else out_dir / f"{cfg.output_slug}-next-human.u8"
        ),
        out_full=(
            Path(out_full)
            if out_full is not None
            else out_dir / f"{cfg.output_slug}-next-full.u8"
        ),
        scope_out=Path(scope_out) if scope_out is not None else out_dir / "scope.md",
    )
