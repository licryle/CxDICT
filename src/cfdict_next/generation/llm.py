"""OpenAI-compatible LLM client for batch definition generation.

Sends batches of entries (each with its full gloss list), validates the
JSON-array response, and maps each object back onto its entry via the
echoed `id`. Gloss parity is enforced on the response itself: every input
sense must be covered exactly once. A bogus entry salvages instead of
sinking its batch — good entries return, only the bad ones defer to
single retry — while transport and envelope failures still retry the whole
batch up to `max_retries`, then raise GenerationError naming the failure.
Standard library only (`urllib`).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .config import LLMConfig
from .prompt import GenerationItem, render_prompt


class GenerationError(Exception):
    """Raised when a batch cannot be generated or validated."""


@dataclass(frozen=True)
class Sense:
    """One validated definition for one gloss, in the target language."""

    gloss: str
    definition: str


@dataclass(frozen=True)
class GenerationResult:
    """One validated entry: identity plus its full sense list."""

    key: str  # lexical identity "traditional|simplified|pinyin"
    traditional: str
    simplified: str
    pinyin: str
    senses: tuple[Sense, ...]


def post_chat_completions(
    endpoint: str, model: str, system: str, user: str, timeout_s: float
) -> Any:
    """POST one chat-completions request; return the decoded JSON body."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except OSError as exc:
        raise GenerationError(f"LLM request failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"LLM response is not valid JSON: {exc}") from exc


def _extract_content(response: Any) -> str:
    """Pull the assistant message text out of a chat-completions body."""
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GenerationError(
            f"LLM response has no choices[0].message.content: {response!r}"
        ) from exc


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences LLMs add despite 'No markdown' instruction.

    Handles ```json ... ```, ``` ... ```, with leading/trailing whitespace.
    Returns the inner payload unchanged when no fences are present.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # Drop opening fence (``` or ```json + possible trailing text).
    lines = lines[1:]
    # Drop closing fence: last line starting with ``` (or trailing ```).
    while lines and lines[-1].strip() == "":
        lines.pop()
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    else:
        # Closing fence glued to content on the same line.
        joined = "\n".join(lines)
        if "```" in joined:
            joined = joined.rsplit("```", 1)[0]
        return joined.strip()
    return "\n".join(lines).strip()


def _parse_content(content: str) -> Any:
    """Parse assistant message text as JSON, tolerating code fences."""
    try:
        return json.loads(_strip_code_fences(content))
    except json.JSONDecodeError as exc:
        raise GenerationError(
            f"LLM message content is not a JSON array: {content[:200]!r}"
        ) from exc


def _validate_senses(item: GenerationItem, obj: Any, entry_id: int) -> tuple[Sense, ...]:
    """Validate one entry's senses array against its input glosses."""
    senses = obj.get("senses") if isinstance(obj, dict) else None
    if not isinstance(senses, list) or not senses:
        raise GenerationError(f"LLM response id {entry_id}: 'senses' must be a non-empty array")
    seen: dict[str, str] = {}
    for sense in senses:
        if not isinstance(sense, dict):
            raise GenerationError(
                f"LLM response id {entry_id}: sense must be an object, got {sense!r}"
            )
        gloss = sense.get("gloss")
        definition = sense.get("definition")
        if not isinstance(gloss, str) or not gloss.strip():
            raise GenerationError(
                f"LLM response id {entry_id}: sense has empty 'gloss'"
            )
        if not isinstance(definition, str) or not definition.strip():
            raise GenerationError(
                f"LLM response id {entry_id}: sense {gloss!r} has empty 'definition'"
            )
        if gloss in seen:
            raise GenerationError(
                f"LLM response id {entry_id}: duplicate sense for {gloss!r}"
            )
        seen[gloss] = definition.strip()
    expected = set(item.glosses)
    missing = expected - set(seen)
    extra = set(seen) - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"dropped sense(s): {sorted(missing)}")
        if extra:
            details.append(f"invented sense(s): {sorted(extra)}")
        raise GenerationError(
            f"LLM response id {entry_id} ({item.simplified}): gloss parity failure — "
            + "; ".join(details)
        )
    return tuple(Sense(gloss=gloss, definition=seen[gloss]) for gloss in item.glosses)


@dataclass(frozen=True)
class BatchOutcome:
    """One batch attempt cycle: good results plus deferrals.

    `failed` holds the entries to defer to single retry; `causes` maps each
    failed entry's key to its validation error. Empty `failed` means the
    whole batch validated.
    """

    results: list[GenerationResult]
    failed: list[GenerationItem]
    causes: dict[str, str]


def _check_envelope(raw: Any, n: int) -> dict[Any, Any]:
    """Validate the response envelope; return objects keyed by id.

    Raises GenerationError: envelope problems cannot be attributed to one
    entry, so the whole batch must retry.
    """
    if not isinstance(raw, list):
        raise GenerationError(
            "LLM response must be a JSON array, "
            f"got {type(raw).__name__}: {str(raw)[:200]!r}"
        )
    by_id: dict[Any, Any] = {}
    for obj in raw:
        if not isinstance(obj, dict) or "id" not in obj:
            raise GenerationError(f"LLM response object has no 'id': {obj!r}")
        if obj["id"] in by_id:
            raise GenerationError(f"LLM response repeats id {obj['id']!r}")
        by_id[obj["id"]] = obj
    extra = set(by_id) - set(range(n))
    if extra:
        raise GenerationError(f"LLM response has unknown ids: {sorted(extra)}")
    return by_id


def _validate_item(
    item: GenerationItem, obj: Any, index: int
) -> GenerationResult:
    """Validate one entry's response object; raise on any mismatch."""
    word = obj.get("word")
    if word != item.simplified:
        raise GenerationError(
            f"LLM response id {index}: word {word!r} does not match "
            f"requested {item.simplified!r} — mapping unsafe"
        )
    senses = _validate_senses(item, obj, index)
    return GenerationResult(
        key=item.key,
        traditional=item.traditional,
        simplified=item.simplified,
        pinyin=item.pinyin,
        senses=senses,
    )


def _split_batch(
    items: list[GenerationItem], by_id: dict[Any, Any]
) -> BatchOutcome:
    """Split one validated envelope into good results and deferrals.

    Never raises: every per-entry problem (missing id, word mismatch,
    gloss parity) lands in `failed` with its cause.
    """
    results: list[GenerationResult] = []
    failed: list[GenerationItem] = []
    causes: dict[str, str] = {}
    for i, item in enumerate(items):
        if i not in by_id:
            failed.append(item)
            causes[item.key] = (
                f"LLM response is missing id {i} ({item.simplified})"
            )
            continue
        try:
            results.append(_validate_item(item, by_id[i], i))
        except GenerationError as exc:
            failed.append(item)
            causes[item.key] = str(exc)
    return BatchOutcome(results=results, failed=failed, causes=causes)


def generate_batch(
    items: list[GenerationItem],
    config: LLMConfig,
    post: Callable[..., Any] = post_chat_completions,
) -> BatchOutcome:
    """Generate definitions for one batch of entries, with retries.

    `post` is injectable so tests run without a network. Transport and
envelope failures retry the whole batch up to `max_retries`, then raise
GenerationError (nothing salvageable). Per-entry failures on a
multi-entry batch salvage immediately — good entries return, bad ones
defer — because a poison entry would otherwise burn whole-batch retries
for everyone; the deferred singles still get their own retries from the
caller. A single-entry batch retries per-entry failures too, then raises.
    """
    if not items:
        raise GenerationError("cannot generate an empty batch")
    for item in items:
        if not item.glosses:
            raise GenerationError(f"entry {item.key}: no glosses to generate")
    system, user = render_prompt(items)
    attempts = config.max_retries + 1
    last_error: GenerationError | None = None
    for _ in range(attempts):
        try:
            response = post(
                config.endpoint, config.model, system, user, config.timeout_s
            )
            content = _extract_content(response)
            raw = _parse_content(content)
            by_id = _check_envelope(raw, len(items))
        except GenerationError as exc:
            last_error = exc
            continue
        outcome = _split_batch(items, by_id)
        if not outcome.failed or len(items) > 1:
            return outcome
        last_error = GenerationError(outcome.causes[items[0].key])
    raise GenerationError(
        f"batch failed after {attempts} attempt(s): {last_error}"
    )
