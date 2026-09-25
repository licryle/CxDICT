"""Prompt construction for definition generation (Phase 5, spec §6).

Prompts are per entry, not per gloss: one entry (with its full gloss list)
maps to one response object (with its full sense list). This keeps senses
differentiated and makes gloss parity checkable on the response itself.

Templates and few-shot examples live OUTSIDE this package, in
child-owned ``<lang-dir>/<code>/`` directories (see
``cxdict.languages``): the exact wording is versioned with the
language data (spec §16: the prompt version is part of release
provenance). Nothing here reads files at import time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..languages import get_language


@dataclass(frozen=True)
class GenerationItem:
    """One entry to generate: an identity plus its full CEDICT gloss list."""

    key: str  # lexical identity "traditional|simplified|pinyin"
    traditional: str
    simplified: str
    pinyin: str
    glosses: tuple[str, ...]


def _split_segments(text: str) -> tuple[str, ...]:
    """Split a '/'-separated gloss string (CEDICT segmentation)."""
    return tuple(s.strip() for s in text.split("/") if s.strip())


def load_few_shot_for(code: str) -> tuple[list[GenerationItem], list[dict]]:
    """Load curated examples for one language; enforce gloss parity.

    The curated pairs must satisfy gloss parity themselves — the model is
    shown nothing the validator would reject. tests/test_generation.py
    enforces all this.
    """
    import json

    from ..identity import compute_lexical_identity

    path = get_language(code).few_shot
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


def template_path_for(code: str):
    """Path of the versioned prompt template for one language."""
    return get_language(code).prompt_template


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
