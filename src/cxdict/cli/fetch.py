"""Fetch CLI: download the current MDBG snapshot into the dated log.

Usage:
    python scripts/fetch_cc_cedict.py [--cc-cedict-dir DIR] [--url URL]
                                      [--source PATH] [--timeout SECS] [--dry-run]

Compares the download against the logged snapshots by canonical content
hash (robust to gzip-header churn): identical content means "up to date"
even when the served bytes differ. New content is stored decompressed as
YYYY-MM-DD.u8 (upstream #! date; -02/-03 suffix on same-day collisions)
and logged in snapshots.toml. --source reads a
local .gz file instead of downloading (offline refresh, tests). --dry-run
prints the plan without writing anything. The pipeline itself never
fetches; it only reads committed files.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import ensure_utf8_output
from ..parser.u8 import DictionaryEntry, parse_u8_line
from ..snapshots import (
    Snapshot,
    append_snapshot,
    canonical_content_hash,
    canonical_hash_of_rows,
    load_manifest,
)

MDBG_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
HEADER_SCAN_LINES = 80


class FetchError(Exception):
    """A fetch step failed; the message names which one."""


@dataclass
class FetchPlan:
    """Assessed download; no writes performed to reach it."""

    status: str  # "up-to-date" | "new"
    date: str
    upstream_date: str
    upstream_time: int
    upstream_sha256: str
    content_sha256: str
    entries: int
    pairs: int
    target_file: str
    reason: str


def download_bytes(url: str, timeout: int) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except (OSError, ValueError) as exc:
        raise FetchError(f"download failed ({url}): {exc}") from exc


def parse_snapshot_text(text: str) -> list[DictionaryEntry]:
    """Parse decompressed snapshot text; fail on any malformed row."""
    by_id: dict[str, DictionaryEntry] = {}
    errors = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        try:
            entry = parse_u8_line(raw)
        except ValueError as exc:
            errors.append((lineno, str(exc)))
            continue
        if entry is None:
            continue
        lid = entry.lexical_id()
        if lid in by_id:
            existing = by_id[lid]
            merged = tuple(sorted(set(existing.definitions + entry.definitions)))
            by_id[lid] = DictionaryEntry(
                existing.traditional, existing.simplified, existing.pinyin, merged
            )
        else:
            by_id[lid] = entry
    if errors:
        preview = "; ".join(f"line {n}: {msg}" for n, msg in errors[:5])
        raise FetchError(f"snapshot has {len(errors)} malformed row(s): {preview}")
    return list(by_id.values())


def read_upstream_header(text: str) -> tuple[str, int]:
    """Upstream #! date/time; the date names the snapshot file."""
    date = None
    time = 0
    for line in text.splitlines()[:HEADER_SCAN_LINES]:
        if line.startswith("#! date="):
            date = line[len("#! date="):].strip()
        elif line.startswith("#! time="):
            try:
                time = int(line[len("#! time="):].strip())
            except ValueError:
                time = 0
    if date is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", date):
        raise FetchError("snapshot has no usable '#! date=' header — cannot name the file")
    return date, time


def plan_fetch(gz_bytes: bytes, cc_dir: str | Path) -> tuple[FetchPlan, bytes]:
    """Compare a download against the log; performs no writes."""
    cc_dir = Path(cc_dir)
    try:
        raw = gzip.decompress(gz_bytes)
    except (OSError, EOFError) as exc:
        raise FetchError(f"download is not a gzip file: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FetchError(f"snapshot is not UTF-8: {exc}") from exc
    upstream_date, upstream_time = read_upstream_header(text)
    entries = parse_snapshot_text(text)
    rows = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    content = canonical_hash_of_rows(rows)
    pairs = len({(e.traditional, e.simplified) for e in entries})
    upstream_sha = hashlib.sha256(gz_bytes).hexdigest()
    date = upstream_date[:10]

    try:
        snapshots = load_manifest(cc_dir)
    except FileNotFoundError:
        snapshots = []
    latest = snapshots[0] if snapshots else None
    if latest is not None and content == latest.content_sha256:
        return FetchPlan(
            status="up-to-date", date=date, upstream_date=upstream_date,
            upstream_time=upstream_time, upstream_sha256=upstream_sha,
            content_sha256=content, entries=len(entries), pairs=pairs,
            target_file=latest.file,
            reason=f"content identical to logged snapshot {latest.date}",
        ), raw

    target = f"{date}.u8"
    suffix = 2
    while (cc_dir / target).is_file():
        if canonical_content_hash(cc_dir / target) == content:
            return FetchPlan(
                status="up-to-date", date=date, upstream_date=upstream_date,
                upstream_time=upstream_time, upstream_sha256=upstream_sha,
                content_sha256=content, entries=len(entries), pairs=pairs,
                target_file=target,
                reason=f"content already stored as {target}",
            ), raw
        if suffix > 99:
            raise FetchError(f"too many same-day snapshots for {date}")
        target = f"{date}-{suffix:02d}.u8"
        suffix += 1

    return FetchPlan(
        status="new", date=date, upstream_date=upstream_date,
        upstream_time=upstream_time, upstream_sha256=upstream_sha,
        content_sha256=content, entries=len(entries), pairs=pairs,
        target_file=target,
        reason=f"new content for {date}",
    ), raw


def apply_plan(plan: FetchPlan, cc_dir: str | Path, raw: bytes) -> Snapshot:
    """Store the snapshot file and log it; caller checked status == 'new'."""
    cc_dir = Path(cc_dir)
    cc_dir.mkdir(parents=True, exist_ok=True)
    (cc_dir / plan.target_file).write_bytes(raw)
    snapshot = Snapshot(
        date=plan.date, file=plan.target_file, upstream_date=plan.upstream_date,
        upstream_time=plan.upstream_time, upstream_sha256=plan.upstream_sha256,
        content_sha256=plan.content_sha256, entries=plan.entries, pairs=plan.pairs,
    )
    append_snapshot(cc_dir, snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--cc-cedict-dir", default="dictionaries/cc-cedict")
    parser.add_argument("--url", default=MDBG_URL)
    parser.add_argument("--source", default=None,
                        help="local .gz file instead of downloading (offline refresh)")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.source:
            try:
                gz_bytes = Path(args.source).read_bytes()
            except OSError as exc:
                raise FetchError(f"cannot read --source: {exc}") from exc
        else:
            gz_bytes = download_bytes(args.url, args.timeout)
        plan, raw = plan_fetch(gz_bytes, args.cc_cedict_dir)
    except FetchError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    print(f"fetch: {plan.status} — {plan.reason}")
    print(f"  upstream: {plan.upstream_date} (time {plan.upstream_time})")
    print(f"  content: {plan.content_sha256[:12]} "
          f"rows={plan.entries} pairs={plan.pairs}")
    if args.dry_run:
        print(f"  dry run — nothing written (would store {plan.target_file})")
        return 0
    if plan.status == "up-to-date":
        return 0
    try:
        apply_plan(plan, args.cc_cedict_dir, raw)
    except (OSError, ValueError) as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    print(f"  wrote {plan.target_file} + manifest entry")
    return 0
