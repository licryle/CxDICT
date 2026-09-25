"""Prompt construction for definition generation (Phase 5, spec §6).

Prompts are per entry, not per gloss: one entry (with its full gloss list)
maps to one response object (with its full sense list). This keeps senses
differentiated and makes gloss parity checkable on the response itself.

Each target language owns its template + few-shot assets under
`generation/assets/<code>/`, registered in `cfdict_next.languages`
(spec §16: the prompt version is part of release provenance).
`PROMPT_VERSION` below is the French version; other languages carry their
own version from the registry (used by P4 generation wiring).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..languages import get_language

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# French defaults (backward compatible while P4 wires --language through).
PROMPT_VERSION = "v6"
TEMPLATE_NAME = "fr/generate_fr_v6.txt"

# Few-shot examples live below (EXAMPLE_ITEMS / EXAMPLE_OUTPUTS), defined
# after GenerationItem so the examples themselves are real items the
# validator accepts — tests/test_generation.py runs them through it.
# These module-level names are the French examples (backward compat);
# other languages load via load_few_shot_for().


@dataclass(frozen=True)
class GenerationItem:
    """One entry to generate: an identity plus its full CEDICT gloss list."""

    key: str  # lexical identity "traditional|simplified|pinyin"
    traditional: str
    simplified: str
    pinyin: str
    glosses: tuple[str, ...]


# Few-shot examples: curated per-language pairs in
# generation/assets/<code>/few_shot_examples.json ("english"/"definition"
# split on "/" into glosses). The curated pairs must satisfy gloss parity
# themselves — the model is shown nothing the validator would reject.
# tests/test_generation.py enforces all this.
FEW_SHOT_PATH = "fr/few_shot_examples.json"


def _split_segments(text: str) -> tuple[str, ...]:
    """Split a '/'-separated gloss string (CEDICT segmentation)."""
    return tuple(s.strip() for s in text.split("/") if s.strip())


def load_few_shot_for(code: str) -> tuple[list[GenerationItem], list[dict]]:
    """Load curated examples for one language; enforce gloss parity."""
    import json

    from ..identity import compute_lexical_identity

    cfg = get_language(code)
    path = ASSETS_DIR / cfg.few_shot
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list[GenerationItem] = []
    outputs: list[dict] = []
    for n, example in enumerate(raw):
        glosses = _split_segments(example["english"])
        defs = _split_segments(example["definition"])
        if len(glosses) != len(defs):
            raise ValueError(
                f"few-shot example {n} ({example['simplified']}): "
                f"{len(glosses)} gloss vs {len(defs)} definition segments"
            )
        key = compute_lexical_identity(
            example["traditional"], example["simplified"], example["pinyin"]
        )
        items.append(
            GenerationItem(
                key=key,
                traditional=example["traditional"],
                simplified=example["simplified"],
                pinyin=example["pinyin"],
                glosses=glosses,
            )
        )
        outputs.append(
            {
                "id": n,
                "word": example["simplified"],
                "senses": [
                    {"gloss": gloss, "definition": definition}
                    for gloss, definition in zip(glosses, defs)
                ],
            }
        )
    return items, outputs


EXAMPLE_ITEMS, EXAMPLE_OUTPUTS = load_few_shot_for("fr")


def _render_example_lines(
    items: list[GenerationItem], outputs: list[dict]
) -> str:
    import json

    lines = []
    for item, output in zip(items, outputs):
        gloss_lines = "\n".join(f'   - "{gloss}"' for gloss in item.glosses)
        lines.append(
            f"Input:  [{output['id']}] {item.simplified} "
            f"({item.traditional}, {item.pinyin}) — senses:\n{gloss_lines}"
        )
        lines.append(f"Output: [{json.dumps(output, ensure_ascii=False)}]")
    return "\n".join(lines)


EXAMPLE_LINES = _render_example_lines(EXAMPLE_ITEMS, EXAMPLE_OUTPUTS)


def template_path_for(code: str) -> Path:
    """Path of the versioned prompt template for one language."""
    return ASSETS_DIR / get_language(code).prompt_template


def prompt_template_path() -> Path:
    """Path of the French versioned prompt template (backward compat)."""
    return ASSETS_DIR / TEMPLATE_NAME


def render_prompt(items: list[GenerationItem], language: str) -> tuple[str, str]:
    """Render (system_prompt, user_message) for one batch of entries.

    `language` is required (no default): the caller must say which
    dictionary is being generated. Entries are numbered [0..n) in order;
    the model must echo each id and cover each entry's senses exactly,
    so responses map back unambiguously.
    """
    cfg = get_language(language)
    template = template_path_for(language).read_text(encoding="utf-8")
    example_items, example_outputs = load_few_shot_for(language)
    system = template.replace(
        "{example_lines}",
        _render_example_lines(example_items, example_outputs),
    )
    blocks = []
    for i, item in enumerate(items):
        gloss_lines = "\n".join(f'   - "{gloss}"' for gloss in item.glosses)
        blocks.append(
            f"[{i}] {item.simplified} ({item.traditional}, {item.pinyin})"
            f" — senses:\n{gloss_lines}"
        )
    user = cfg.prompt_user_intro + "\n".join(blocks)
    return system, user
