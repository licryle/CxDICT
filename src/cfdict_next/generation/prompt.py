"""Prompt construction for French-definition generation (Phase 5, spec §6).

Prompts are per entry, not per gloss: one entry (with its full gloss list)
maps to one response object (with its full sense list). This keeps senses
differentiated and makes gloss parity checkable on the response itself.

The prompt template lives in `src/generation/assets/` so the exact wording is versioned
with the code (spec §16: the prompt version is part of release provenance).
`PROMPT_VERSION` is recorded on every generated record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_VERSION = "v6"
TEMPLATE_NAME = "generate_fr_v6.txt"

# Few-shot examples live below (EXAMPLE_ITEMS / EXAMPLE_OUTPUTS), defined
# after GenerationItem so the examples themselves are real items the
# validator accepts — tests/test_generation.py runs them through it.


@dataclass(frozen=True)
class GenerationItem:
    """One entry to generate: an identity plus its full CEDICT gloss list."""

    key: str  # lexical identity "traditional|simplified|pinyin"
    traditional: str
    simplified: str
    pinyin: str
    glosses: tuple[str, ...]


# Few-shot examples: curated user-supplied pairs in
# src/generation/assets/few_shot_examples.json (english/fr split on "/" into glosses).
# The curated pairs must satisfy gloss parity themselves — the model is
# shown nothing the validator would reject. tests/test_generation.py
# enforces all this.
FEW_SHOT_PATH = "few_shot_examples.json"


def _split_segments(text: str) -> tuple[str, ...]:
    """Split a '/'-separated gloss string (CEDICT segmentation)."""
    return tuple(s.strip() for s in text.split("/") if s.strip())


def _load_few_shot() -> tuple[list[GenerationItem], list[dict]]:
    """Load curated examples; enforce gloss parity on the curated data."""
    import json

    from ..identity import compute_lexical_identity

    path = Path(__file__).resolve().parent / "assets" / FEW_SHOT_PATH
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


EXAMPLE_ITEMS, EXAMPLE_OUTPUTS = _load_few_shot()


def _render_example_lines() -> str:
    import json

    lines = []
    for item, output in zip(EXAMPLE_ITEMS, EXAMPLE_OUTPUTS):
        gloss_lines = "\n".join(f'   - "{gloss}"' for gloss in item.glosses)
        lines.append(
            f"Input:  [{output['id']}] {item.simplified} "
            f"({item.traditional}, {item.pinyin}) — senses:\n{gloss_lines}"
        )
        lines.append(f"Output: [{json.dumps(output, ensure_ascii=False)}]")
    return "\n".join(lines)


EXAMPLE_LINES = _render_example_lines()


def prompt_template_path() -> Path:
    """Path of the versioned prompt template."""
    return Path(__file__).resolve().parent / "assets" / TEMPLATE_NAME


def render_prompt(items: list[GenerationItem]) -> tuple[str, str]:
    """Render (system_prompt, user_message) for one batch of entries.

    Entries are numbered [0..n) in order; the model must echo each id and
    cover each entry's senses exactly, so responses map back unambiguously.
    """
    template = prompt_template_path().read_text(encoding="utf-8")
    system = template.replace("{example_lines}", EXAMPLE_LINES)
    blocks = []
    for i, item in enumerate(items):
        gloss_lines = "\n".join(f'   - "{gloss}"' for gloss in item.glosses)
        blocks.append(
            f"[{i}] {item.simplified} ({item.traditional}, {item.pinyin})"
            f" — senses:\n{gloss_lines}"
        )
    user = (
        "Translate the meanings of the Chinese entries below into French.\n"
        "Entries to translate:\n" + "\n".join(blocks)
    )
    return system, user
