"""Tests for the CC-CEDICT fetch flow (src/cxdict/cli/fetch.py)."""

import gzip

from cxdict.cli.fetch import main
from cxdict.languages import resolve_cc_cedict
from cxdict.snapshots import canonical_content_hash, latest_snapshot, load_manifest

HEADER = "# CC-CEDICT\n#! date={date}T07:35:13Z\n#! time=42\n"
ROWS_A = ["中 中 [Zhong1] /middle/", "美 美 [Mei3] /beautiful/"]
ROWS_B = ["中 中 [Zhong1] /middle/", "大 大 [Da4] /big/"]


def make_gz(date, rows):
    return gzip.compress((HEADER.format(date=date) + "\n".join(rows) + "\n").encode())


def write_snapshot(cc, date, rows):
    (cc / f"{date}.u8").write_text(
        HEADER.format(date=date) + "\n".join(rows) + "\n", encoding="utf-8"
    )


def write_manifest(cc, specs):
    """specs: [(date, rows)] newest first; content hashes computed for real."""
    blocks = []
    for date, rows in specs:
        write_snapshot(cc, date, rows)
        content = canonical_content_hash(cc / f"{date}.u8")
        blocks.append(
            "[[snapshot]]\n"
            f'date = "{date}"\nfile = "{date}.u8"\n'
            f'upstream_date = "{date}T07:35:13Z"\nupstream_time = 42\n'
            'upstream_sha256 = "00"\n'
            f'content_sha256 = "{content}"\n'
            f"entries = {len(rows)}\npairs = {len(rows)}\n"
        )
    (cc / "snapshots.toml").write_text(
        "# log\n\n" + "\n".join(blocks), encoding="utf-8"
    )


def run(cc, tmp_path, gz_bytes, *extra):
    src = tmp_path / "dl.txt.gz"
    src.write_bytes(gz_bytes)
    return main(["--cc-cedict-dir", str(cc), "--source", str(src), *extra])


def test_up_to_date_same_content_writes_nothing(tmp_path, capsys):
    cc = tmp_path / "cc"
    cc.mkdir()
    write_manifest(cc, [("2026-09-12", ROWS_A)])
    before = (cc / "snapshots.toml").read_text(encoding="utf-8")
    assert run(cc, tmp_path, make_gz("2026-09-12", ROWS_A)) == 0
    assert "up-to-date" in capsys.readouterr().out
    assert (cc / "snapshots.toml").read_text(encoding="utf-8") == before
    assert sorted(p.name for p in cc.iterdir()) == ["2026-09-12.u8", "snapshots.toml"]


def test_new_snapshot_stored_and_logged(tmp_path, capsys):
    cc = tmp_path / "cc"
    cc.mkdir()
    write_manifest(cc, [("2026-09-12", ROWS_A)])
    assert run(cc, tmp_path, make_gz("2026-09-20", ROWS_B)) == 0
    out = capsys.readouterr().out
    assert "new content for 2026-09-20" in out
    stored = (cc / "2026-09-20.u8").read_bytes()
    assert stored == gzip.decompress((tmp_path / "dl.txt.gz").read_bytes())
    logged = load_manifest(cc)
    assert [s.date for s in logged] == ["2026-09-20", "2026-09-12"]
    assert logged[0].entries == 2 and logged[0].upstream_sha256 != "00"


def test_dry_run_writes_nothing(tmp_path, capsys):
    cc = tmp_path / "cc"
    cc.mkdir()
    write_manifest(cc, [("2026-09-12", ROWS_A)])
    assert run(cc, tmp_path, make_gz("2026-09-20", ROWS_B), "--dry-run") == 0
    assert "dry run" in capsys.readouterr().out
    assert sorted(p.name for p in cc.iterdir()) == ["2026-09-12.u8", "snapshots.toml"]
    assert len(load_manifest(cc)) == 1


def test_same_day_collision_gets_suffix(tmp_path):
    cc = tmp_path / "cc"
    cc.mkdir()
    write_manifest(cc, [("2026-09-12", ROWS_A)])
    # Same upstream date, different content: the dated file is taken.
    (cc / "2026-09-20.u8").write_text(
        HEADER.format(date="2026-09-20") + "舊 舊 [Jiu4] /old/\n", encoding="utf-8"
    )
    assert run(cc, tmp_path, make_gz("2026-09-20", ROWS_B)) == 0
    assert (cc / "2026-09-20-02.u8").is_file()
    logged = load_manifest(cc)
    assert logged[0].file == "2026-09-20-02.u8"


def test_first_snapshot_bootstraps_manifest(tmp_path, capsys):
    cc = tmp_path / "cc"
    cc.mkdir()
    assert run(cc, tmp_path, make_gz("2026-09-20", ROWS_B)) == 0
    out = capsys.readouterr().out
    assert "new content for 2026-09-20" in out
    assert [s.date for s in load_manifest(cc)] == ["2026-09-20"]


def manifest_block(date, rows, cc):
    return (
        "[[snapshot]]\n"
        f'date = "{date}"\nfile = "{date}.u8"\n'
        f'upstream_date = "{date}T07:35:13Z"\nupstream_time = 42\n'
        'upstream_sha256 = "00"\n'
        f'content_sha256 = "{canonical_content_hash(cc / f"{date}.u8")}"\n'
        f"entries = {len(rows)}\npairs = {len(rows)}\n"
    )


def test_latest_is_by_date_never_by_file_position(tmp_path, capsys):
    """Manifest listed oldest-first: latest is still by date everywhere."""
    cc = tmp_path / "cc"
    cc.mkdir()
    write_snapshot(cc, "2025-08-08", ROWS_A)
    write_snapshot(cc, "2026-09-12", ROWS_B)
    (cc / "snapshots.toml").write_text(
        "# oldest first on purpose\n\n"
        + manifest_block("2025-08-08", ROWS_A, cc)
        + "\n"
        + manifest_block("2026-09-12", ROWS_B, cc),
        encoding="utf-8",
    )
    assert latest_snapshot(cc).date == "2026-09-12"
    assert resolve_cc_cedict(cc) == cc / "2026-09-12.u8"
    # Newest content: up-to-date against 2026-09-12, nothing written.
    assert run(cc, tmp_path, make_gz("2026-09-12", ROWS_B)) == 0
    assert "logged snapshot 2026-09-12" in capsys.readouterr().out
    assert sorted(p.name for p in cc.iterdir()) == [
        "2025-08-08.u8", "2026-09-12.u8", "snapshots.toml",
    ]
    # Older content: never mistaken for latest, manifest untouched.
    assert run(cc, tmp_path, make_gz("2025-08-08", ROWS_A)) == 0
    assert "already stored as 2025-08-08.u8" in capsys.readouterr().out
    assert [s.date for s in load_manifest(cc)] == ["2026-09-12", "2025-08-08"]
    # Brand-new content appends last in file yet becomes the latest.
    rows_c = ROWS_B + ["Z Z [P9] /zee/"]
    assert run(cc, tmp_path, make_gz("2026-09-20", rows_c)) == 0
    assert latest_snapshot(cc).date == "2026-09-20"
    assert resolve_cc_cedict(cc) == cc / "2026-09-20.u8"
    assert run(cc, tmp_path, make_gz("2026-09-20", rows_c)) == 0
    assert "logged snapshot 2026-09-20" in capsys.readouterr().out


def test_bad_gzip_missing_header_and_malformed_rows_fail(tmp_path, capsys):
    cc = tmp_path / "cc"
    cc.mkdir()
    assert run(cc, tmp_path, b"not a gzip file") == 1
    assert "not a gzip" in capsys.readouterr().err
    no_header = gzip.compress(b"# nothing here\nA A [x] /y/\n")
    assert run(cc, tmp_path, no_header) == 1
    assert "no usable '#! date=' header" in capsys.readouterr().err
    bad_row = gzip.compress(
        (HEADER.format(date="2026-09-20") + "this is not an entry\n").encode()
    )
    assert run(cc, tmp_path, bad_row) == 1
    assert "malformed row" in capsys.readouterr().err
    assert list(cc.iterdir()) == []
