"""CC-CEDICT snapshot log and stable version identity.

Snapshots live in dictionaries/cc-cedict/ as YYYY-MM-DD.u8, logged newest
first in snapshots.toml. A snapshot's *version* is
``cc-cedict:YYYY-MM-DD:<content-hash12>`` where the content hash runs over
the normalized entry rows (sorted, CRLF-insensitive, comments and blank
lines excluded) — so the same upstream snapshot keeps its identity across
storage formats (.gz vs .u8, LF vs CRLF).

Files not listed in the manifest (ad-hoc or fixture files) fall back to
the legacy ``sha256:<file-bytes12>`` form. Pre-manifest record stamps
(full .gz byte hashes, and their scope.md-style ``sha256:<12>`` prefixes)
resolve to snapshot dates through the manifest's ``legacy_shas`` map.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .parser.u8 import iter_u8_lines

MANIFEST_FILENAME = "snapshots.toml"


@dataclass(frozen=True)
class Snapshot:
    """One logged CC-CEDICT snapshot (one [[snapshot]] table)."""

    date: str
    file: str
    upstream_date: str
    upstream_time: int
    upstream_sha256: str = ""
    content_sha256: str = ""
    entries: int = 0
    pairs: int = 0


_REQUIRED_FIELDS = (
    "date",
    "file",
    "upstream_date",
    "upstream_time",
    "content_sha256",
    "entries",
    "pairs",
)
# upstream_sha256 is optional: the base version predates fetch logging.


def load_manifest(cc_dir: str | Path) -> list[Snapshot]:
    """Read snapshots.toml, sorted newest (date) first.

    Sorting is by the ``date`` field, not file position: an appended entry
    (the natural way to log a fresh fetch) still becomes the newest
    snapshot, so nothing downstream can silently build on a stale layer.
    """
    manifest = Path(cc_dir) / MANIFEST_FILENAME
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"CC-CEDICT manifest not found: {manifest}")
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid CC-CEDICT manifest {manifest}: {exc}")
    snapshots = []
    for i, raw in enumerate(data.get("snapshot", [])):
        missing = [k for k in _REQUIRED_FIELDS if k not in raw]
        if missing:
            raise ValueError(
                f"invalid CC-CEDICT manifest {manifest}: "
                f"snapshot #{i} missing {missing}"
            )
        snapshots.append(
            Snapshot(
                **{k: raw[k] for k in _REQUIRED_FIELDS},
                upstream_sha256=raw.get("upstream_sha256", ""),
            )
        )
    # ISO dates sort chronologically; newest first regardless of file order.
    snapshots.sort(key=lambda s: s.date, reverse=True)
    return snapshots


def load_legacy_shas(cc_dir: str | Path) -> dict[str, str]:
    """Return the manifest's full-sha -> date map ({} when absent)."""
    manifest = Path(cc_dir) / MANIFEST_FILENAME
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    legacy = data.get("legacy_shas", {})
    if not isinstance(legacy, dict):
        raise ValueError(f"invalid CC-CEDICT manifest {manifest}: legacy_shas must be a table")
    return dict(legacy)


def latest_snapshot(cc_dir: str | Path) -> Snapshot:
    """Return the newest logged snapshot; raise when the log is empty."""
    snapshots = load_manifest(cc_dir)
    if not snapshots:
        raise ValueError(f"CC-CEDICT manifest is empty: {cc_dir}")
    return snapshots[0]


def canonical_hash_of_rows(rows: Iterable[str]) -> str:
    """SHA-256 over entry rows: sorted, LF-joined.

    Callers pass raw row strings (line breaks stripped, comments and blank
    lines already excluded); see canonical_content_hash for files.
    """
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def canonical_content_hash(path: str | Path) -> str:
    """SHA-256 over normalized entry rows: sorted, LF-joined, no comments.

    Insensitive to storage format (.gz vs .u8), line endings (CRLF vs LF),
    comment headers, and row order — so it identifies the upstream snapshot
    rather than our copy of it.
    """
    rows = [
        line.rstrip("\r\n")
        for line in iter_u8_lines(path)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return canonical_hash_of_rows(rows)


def snapshot_version(snapshot: Snapshot) -> str:
    """Stable version label: cc-cedict:YYYY-MM-DD:<content-hash12>."""
    return f"cc-cedict:{snapshot.date}:{snapshot.content_sha256[:12]}"


def version_for_snapshot_file(path: str | Path, manifest_dir: str | Path | None = None) -> str:
    """Version label for a snapshot file, via the manifest when listed.

    Falls back to the legacy ``sha256:<file-bytes12>`` form for files
    outside the log (ad-hoc or fixture files). Raises OSError when the
    file itself cannot be read.
    """
    path = Path(path)
    manifest_dir = Path(manifest_dir) if manifest_dir is not None else path.parent
    manifest = manifest_dir / MANIFEST_FILENAME
    if manifest.is_file():
        try:
            for snapshot in load_manifest(manifest_dir):
                if snapshot.file == path.name:
                    return snapshot_version(snapshot)
        except ValueError:
            pass
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return "sha256:" + digest


def interpret_version(
    version: str, snapshots: list[Snapshot], legacy_shas: dict[str, str]
) -> str | None:
    """Map a version stamp to a snapshot date, or None when unknown.

    Understands the current ``cc-cedict:DATE:HASH12`` scheme (date wins
    when recognized) and legacy ``sha256:`` stamps (full .gz byte hashes
    and their truncated scope.md-style prefixes, via legacy_shas).
    """
    if version.startswith("cc-cedict:"):
        parts = version.split(":")
        if len(parts) == 3:
            _, date, hash12 = parts
            for snapshot in snapshots:
                if snapshot.date == date:
                    return date
            for snapshot in snapshots:
                if snapshot.content_sha256.startswith(hash12):
                    return snapshot.date
        return None
    if version.startswith("sha256:"):
        prefix = version[len("sha256:"):]
        matches = [date for full, date in legacy_shas.items() if full.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
    return None


def format_snapshot_block(snapshot: Snapshot) -> str:
    """Render one [[snapshot]] table in manifest style."""
    return (
        "[[snapshot]]\n"
        f'date = "{snapshot.date}"\n'
        f'file = "{snapshot.file}"\n'
        f'upstream_date = "{snapshot.upstream_date}"\n'
        f"upstream_time = {snapshot.upstream_time}\n"
        f'upstream_sha256 = "{snapshot.upstream_sha256}"\n'
        f'content_sha256 = "{snapshot.content_sha256}"\n'
        f"entries = {snapshot.entries}\n"
        f"pairs = {snapshot.pairs}\n"
    )


def append_snapshot(cc_dir: str | Path, snapshot: Snapshot) -> Path:
    """Append one [[snapshot]] block, creating the log when missing.

    Refuses duplicate filenames and duplicate content hashes (a snapshot
    already logged under another name). Existing file bytes are otherwise
    preserved verbatim — the block is appended, never rewritten.
    """
    cc_dir = Path(cc_dir)
    manifest = cc_dir / MANIFEST_FILENAME
    if manifest.is_file():
        existing = load_manifest(cc_dir)  # corrupt logs raise: never append blindly
        if any(s.file == snapshot.file for s in existing):
            raise ValueError(f"snapshot file already logged: {snapshot.file}")
        if any(s.content_sha256 == snapshot.content_sha256 for s in existing):
            other = next(
                s.date for s in existing if s.content_sha256 == snapshot.content_sha256
            )
            raise ValueError(f"snapshot content already logged as {other}")
        text = manifest.read_text(encoding="utf-8").rstrip("\n") + "\n\n"
    else:
        cc_dir.mkdir(parents=True, exist_ok=True)
        text = (
            "# CC-CEDICT snapshot log.\n"
            "#\n"
            "# Entries may be appended in any order; tooling sorts by date.\n"
            "# See dictionaries/README.md.\n\n"
        )
    manifest.write_text(text + format_snapshot_block(snapshot), encoding="utf-8")
    return manifest
