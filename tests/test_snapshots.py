"""Tests for the CC-CEDICT snapshot log and version identity."""

import gzip
import re

import pytest

from cxdict.snapshots import (
    canonical_content_hash,
    interpret_version,
    latest_snapshot,
    load_legacy_shas,
    load_manifest,
    snapshot_version,
    version_for_snapshot_file,
)

LINES = [
    "# a comment header",
    "",
    "中國 中国 [Zhong1 guo2] /China/Middle Kingdom/",
    "美 美 [Mei3] /beautiful/",
]

MANIFEST = """\
[[snapshot]]
date = "2026-09-12"
file = "2026-09-12.u8"
upstream_date = "2026-09-12T07:35:13Z"
upstream_time = 1789198513
upstream_sha256 = "aa"
content_sha256 = "{new_hash}"
entries = 2
pairs = 2

[[snapshot]]
date = "2025-08-08"
file = "2025-08-08.u8"
upstream_date = "2025-08-08T05:26:26Z"
upstream_time = 1754630786
upstream_sha256 = "bb"
content_sha256 = "{old_hash}"
entries = 1
pairs = 1

[legacy_shas]
"deadbeef1234" = "2026-09-12"
"""


def _write_layout(root, new_text, old_text, manifest=True):
    cc = root / "dictionaries" / "cc-cedict"
    cc.mkdir(parents=True)
    (cc / "2026-09-12.u8").write_text(new_text, encoding="utf-8")
    (cc / "2025-08-08.u8").write_text(old_text, encoding="utf-8")
    if manifest:
        new_hash = canonical_content_hash(cc / "2026-09-12.u8")
        old_hash = canonical_content_hash(cc / "2025-08-08.u8")
        (cc / "snapshots.toml").write_text(
            MANIFEST.format(new_hash=new_hash, old_hash=old_hash), encoding="utf-8"
        )
    return cc


def test_load_manifest_newest_first_with_all_fields(tmp_path):
    cc = _write_layout(tmp_path, "\n".join(LINES) + "\n", LINES[2] + "\n")
    snapshots = load_manifest(cc)
    assert [s.date for s in snapshots] == ["2026-09-12", "2025-08-08"]
    newest = snapshots[0]
    assert newest.file == "2026-09-12.u8"
    assert newest.upstream_sha256 == "aa"
    assert newest.upstream_time == 1789198513
    assert newest.entries == 2 and newest.pairs == 2
    assert latest_snapshot(cc).date == "2026-09-12"


def test_load_manifest_missing_file_and_empty_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nope")
    cc = tmp_path / "empty"
    cc.mkdir()
    (cc / "snapshots.toml").write_text("", encoding="utf-8")
    assert load_manifest(cc) == []
    with pytest.raises(ValueError):
        latest_snapshot(cc)


def test_load_manifest_rejects_incomplete_row(tmp_path):
    cc = tmp_path / "cc"
    cc.mkdir()
    (cc / "snapshots.toml").write_text(
        '[[snapshot]]\ndate = "2026-09-12"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_manifest(cc)


def test_canonical_hash_stable_across_formats_and_headers(tmp_path):
    body = "\n".join(LINES[2:]) + "\n"
    plain = tmp_path / "a.u8"
    plain.write_text(body, encoding="utf-8")
    crlf = tmp_path / "b.u8"
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    reordered = tmp_path / "c.u8"
    reordered.write_text(
        "# different header\n\n" + "\n".join(reversed(LINES[2:])) + "\n",
        encoding="utf-8",
    )
    gz = tmp_path / "d.txt.gz"
    gz.write_bytes(gzip.compress(body.encode("utf-8")))
    assert canonical_content_hash(plain) == canonical_content_hash(crlf)
    assert canonical_content_hash(plain) == canonical_content_hash(reordered)
    assert canonical_content_hash(plain) == canonical_content_hash(gz)
    changed = tmp_path / "e.u8"
    changed.write_text(body + "多 多 [duo1] /many/\n", encoding="utf-8")
    assert canonical_content_hash(changed) != canonical_content_hash(plain)


def test_snapshot_version_format_has_no_legacy_prefix(tmp_path):
    cc = _write_layout(tmp_path, "\n".join(LINES) + "\n", LINES[2] + "\n")
    version = snapshot_version(load_manifest(cc)[0])
    assert re.fullmatch(r"cc-cedict:2026-09-12:[0-9a-f]{12}", version)
    assert "sha256:" not in version


def test_version_for_snapshot_file_listed_and_unlisted(tmp_path):
    cc = _write_layout(tmp_path, "\n".join(LINES) + "\n", LINES[2] + "\n")
    assert version_for_snapshot_file(cc / "2026-09-12.u8").startswith(
        "cc-cedict:2026-09-12:"
    )
    stray = tmp_path / "stray.u8"
    stray.write_text(LINES[2] + "\n", encoding="utf-8")
    assert version_for_snapshot_file(stray).startswith("sha256:")
    with pytest.raises(OSError):
        version_for_snapshot_file(tmp_path / "missing.u8")


def test_interpret_version_current_and_legacy(tmp_path):
    cc = _write_layout(tmp_path, "\n".join(LINES) + "\n", LINES[2] + "\n")
    snapshots = load_manifest(cc)
    legacy = load_legacy_shas(cc)
    current = snapshot_version(snapshots[0])
    assert interpret_version(current, snapshots, legacy) == "2026-09-12"
    assert interpret_version("sha256:deadbeef1234", snapshots, legacy) == "2026-09-12"
    assert interpret_version("sha256:deadbeef", snapshots, legacy) == "2026-09-12"
    assert interpret_version("sha256:0000", snapshots, legacy) is None
    assert interpret_version("whatever", snapshots, legacy) is None
