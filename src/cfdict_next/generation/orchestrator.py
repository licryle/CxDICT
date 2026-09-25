"""Generation orchestrator: missing scope → batches → endpoint → datasets.

Orchestrates the Phase 5 pipeline end to end over real sources:

1. Parse base + human.u8 + CC-CEDICT, load the LLM dataset (all fail-loud).
2. Compute the missing scope (spec §3, §5) and build one item per entry
   with its full CC-CEDICT gloss list.
3. Generate in batches; every successful batch is merged and written
   immediately, so a later failure never discards earlier progress.
4. A bogus entry never sinks its batch: good entries are written at once
   and only the bad ones defer to a retry pass that runs each alone
   (poison isolation). Transport and envelope failures still retry the
   whole batch; keys failing after the retry pass raise GenerationError
   (successes are already on disk, so a re-run resumes the rest).
5. Stamp provenance, merge into the existing file (key collisions
   refused), rewrite atomically per write.

Safety: `limit` caps entries per run (default 20) — a full-scope run
requires passing limit=0 explicitly. `dry_run` plans without touching
the endpoint or the files.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import Any, Callable

from ..cleanup import base_identities
from ..parser.json import load_llm_json
from ..parser.u8 import DictionaryEntry, parse_u8_file
from .config import LLMConfig
from .llm import (
    GenerationError,
    GenerationResult,
    generate_batch,
    post_chat_completions,
)
from .output import Provenance, build_records, merge_records, write_llm_json
from .prompt import GenerationItem


_GREEN, _RED, _BLUE = "32", "31", "34"


def _use_color(stream: Any) -> bool:
    """ANSI colors only on a real terminal, and never with NO_COLOR set."""
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and bool(stream.isatty())


def _short_error(exc: BaseException, limit: int = 160) -> str:
    """One-line, length-capped rendering of an error for status lines."""
    msg = " ".join(str(exc).split())
    return msg if len(msg) <= limit else msg[: limit - 1] + "…"


def _elapsed_hms(start: float) -> str:
    """Elapsed wall-clock time since `start` (monotonic) as HH:MM:SS."""
    seconds = int(time.monotonic() - start)
    return (
        f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    )


@dataclass(frozen=True)
class GenerationPlan:
    """What a run would do (also returned by actual runs)."""

    scoped: int  # entries in missing scope
    limited_to: int  # entries after applying limit (0 = unlimited setting)
    batches: int  # batch calls the run makes/would make


@dataclass(frozen=True)
class GenerationReport:
    """Outcome of an orchestrator run."""

    plan: GenerationPlan
    llm_new: int
    dry_run: bool


def compute_missing_items(
    cc_entries: list[DictionaryEntry],
    base_ids: set[str],
    existing_ids: set[str],
) -> list[GenerationItem]:
    """Build one generation item per missing-scope entry, in CC-CEDICT order."""
    items: list[GenerationItem] = []
    seen: set[str] = set()
    for entry in cc_entries:
        key = entry.lexical_id()
        if key in base_ids or key in existing_ids or key in seen:
            continue
        seen.add(key)
        items.append(
            GenerationItem(
                key=key,
                traditional=entry.traditional,
                simplified=entry.simplified,
                pinyin=entry.pinyin,
                glosses=tuple(entry.definitions),
            )
        )
    return items


def plan_generation(
    items: list[GenerationItem], batch_size: int, limit: int
) -> GenerationPlan:
    """Describe a run without executing it."""
    limited = items if limit <= 0 else items[:limit]
    batches = (len(limited) + batch_size - 1) // batch_size if limited else 0
    return GenerationPlan(scoped=len(items), limited_to=len(limited), batches=batches)


def generate_all(
    items: list[GenerationItem],
    config: LLMConfig,
    provenance: Provenance,
    generation_date: str | None = None,
    post: Callable[..., Any] = post_chat_completions,
    on_batch: Callable[[dict[str, dict[str, Any]]], None] | None = None,
    progress: bool = True,
    stream: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...], dict[str, str]]:
    """Generate all items in batches; return (records, failed, causes).

    `failed` holds the persistently failing keys; `causes` maps each of them
    to a one-line error summary (also printed on its FAILED status line).

    Every successful batch is converted to records and reported through
    `on_batch` immediately, so callers can persist progress as they go.
    A failed batch is deferred to a retry pass that runs each of its items
    alone (batch size 1): batch-mates of a poison entry still succeed, and
    only persistently failing keys land in `failed_keys`. Both transport
    and response-validation errors are retryable — `generate_batch` already
    retries each attempt up to `max_retries` before giving up on it.
    With `progress`, one status line per completed batch attempt goes to
    `stream` (stdout): outcome, processed/error/remaining counts, percent,
    and elapsed HH:MM:SS.
    """
    out = stream if stream is not None else sys.stdout
    total = len(items)
    first_pass_batches = (
        (total + config.batch_size - 1) // config.batch_size if total else 0
    )
    start = time.monotonic()
    color = _use_color(out)
    done = 0
    # Entries whose batch failed count as errors immediately — they sit in
    # the retry queue, and a later single retry moves each one back to done
    # (success) or leaves it here (still failing). done + errors +
    # remaining always equals total.
    errors = 0

    def _paint(code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    def _status(label: str, state: str, reason: str | None = None) -> None:
        # Timestamp leads, counts stay in fixed position, and the failure
        # cause trails at the end so it never breaks the readable prefix.
        stamp = time.strftime("%H:%M:%S", time.localtime())
        remaining = total - done - errors
        pct = round(100 * (done + errors) / total) if total else 100
        tail = f" — {reason}" if reason else ""
        print(
            f"[{stamp}] {label} {state}: "
            f"{_paint(_GREEN, f'{done} processed')} / "
            f"{_paint(_RED, f'{errors} errors')} / "
            f"{_paint(_BLUE, f'{remaining} to process')} / "
            f"{total} total, "
            f"{pct}% in {_elapsed_hms(start)}{tail}",
            file=out,
            flush=True,
        )

    records: dict[str, dict[str, Any]] = {}

    def _absorb(results: list[GenerationResult]) -> None:
        nonlocal done
        new_records = build_records(results, provenance, generation_date)
        records.update(new_records)
        done += len(new_records)
        if on_batch is not None:
            on_batch(new_records)

    deferred: list[GenerationItem] = []
    for index, chunk in enumerate(batched(items, config.batch_size), start=1):
        chunk = list(chunk)
        label = f"Batch {index}/{first_pass_batches}"
        try:
            outcome = generate_batch(chunk, config, post=post)
        except GenerationError as exc:
            # Transport/envelope failure: nothing salvageable, defer all.
            deferred.extend(chunk)
            errors += len(chunk)
            if progress:
                _status(label, "FAILED", reason=_short_error(exc))
            continue
        _absorb(outcome.results)
        if outcome.failed:
            # Bogus entries defer alone; batch-mates are already written.
            deferred.extend(outcome.failed)
            errors += len(outcome.failed)
            if progress:
                first = outcome.failed[0]
                _status(
                    label, "PARTIAL",
                    reason=(
                        f"{len(outcome.failed)} deferred, e.g. "
                        f"{first.key}: "
                        f"{_short_error(outcome.causes[first.key])}"
                    ),
                )
        elif progress:
            _status(label, "succeeded")
    failed_keys: list[str] = []
    causes: dict[str, str] = {}
    for index, item in enumerate(deferred, start=1):
        try:
            _absorb(generate_batch([item], config, post=post).results)
        except GenerationError as exc:
            failed_keys.append(item.key)
            causes[item.key] = _short_error(exc)
            if progress:
                _status(
                    f"Retry {index}/{len(deferred)}", "FAILED",
                    reason=_short_error(exc),
                )
            continue
        errors -= 1
        if progress:
            _status(f"Retry {index}/{len(deferred)}", "succeeded")
    return records, tuple(failed_keys), causes


def generate_files(
    base_path: str | Path,
    cc_cedict_path: str | Path,
    human_path: str | Path,
    llm_generated_path: str | Path,
    config: LLMConfig,
    cc_cedict_version: str,
    limit: int = 20,
    dry_run: bool = False,
    generation_date: str | None = None,
    post: Callable[..., Any] = post_chat_completions,
    progress: bool = True,
    stream: Any | None = None,
) -> GenerationReport:
    """Run generation against on-disk datasets; rewrite them unless dry_run."""
    base_ids = base_identities(base_path)
    cc_entries, errors = parse_u8_file(cc_cedict_path)
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        raise ValueError(
            f"CC-CEDICT has {len(errors)} malformed line(s): {preview}"
        )
    human_entries, human_errors = parse_u8_file(human_path)
    if human_errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in human_errors[:5])
        raise ValueError(
            f"human.u8 has {len(human_errors)} malformed line(s): {preview}"
        )
    human_ids = {e.lexical_id() for e in human_entries}
    llm_generated = load_llm_json(llm_generated_path)

    items = compute_missing_items(
        cc_entries, base_ids, human_ids | set(llm_generated)
    )
    plan = plan_generation(items, config.batch_size, limit)
    if dry_run:
        return GenerationReport(plan=plan, llm_new=0, dry_run=True)

    limited = items if limit <= 0 else items[:limit]
    provenance = Provenance(
        cc_cedict_version=cc_cedict_version, llm_model=config.model
    )

    def _persist(new_records: dict[str, dict[str, Any]]) -> None:
        """Merge one successful batch into the dataset and rewrite the file.

        Per-batch writes (each atomic via temp file + rename) mean a later
        failure keeps earlier progress on disk; the next run's missing-scope
        computation skips everything already written.
        """
        merged = merge_records(llm_generated, new_records)
        write_llm_json(llm_generated_path, merged)
        llm_generated.update(new_records)

    new_records, failed_keys, causes = generate_all(
        limited, config, provenance, generation_date, post,
        on_batch=_persist, progress=progress, stream=stream,
    )
    if failed_keys:
        shown = "; ".join(f"{key}: {causes[key]}" for key in failed_keys[:3])
        if len(failed_keys) > 3:
            shown += f"; and {len(failed_keys) - 3} more"
        raise GenerationError(
            f"{len(failed_keys)} entr{'y' if len(failed_keys) == 1 else 'ies'} "
            f"failed after retry, e.g. {failed_keys[0]!r} — "
            f"{len(new_records)} succeeded and were "
            f"written; re-run resumes the rest. Causes: {shown}"
        )
    return GenerationReport(plan=plan, llm_new=len(new_records), dry_run=False)
