"""Tests for the release workflow (Phase 10, spec §13).

Two levels: the workflow file itself is structurally asserted (triggers,
jobs, ordering, permissions), and the exact pipeline it runs — validate,
assemble, validate outputs, scope info — is executed end to end as
subprocesses on fixture data, so the tested commands are literally the
ones in the YAML.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "assemble.yml"

BASE_SAMPLE = "中國 中国 [Zhong1 guo2] /Chine/\n"
HUMAN_SAMPLE = "美 美 [Mei3] /beau/\n"
CC_SAMPLE = (
    "中國 中国 [Zhong1 guo2] /China/Middle Kingdom/\n"
    "美 美 [Mei3] /beautiful/\n"
    "行 行 [Xing2] /to walk/\n"
    "學 学 [Xue2] /to study/\n"
)


def record_for(key, glosses):
    trad, simp, pin = key.split("|")
    return {
        "traditional": trad,
        "simplified": simp,
        "pinyin": pin,
        "senses": [{"source_gloss": g, "definition": f"fr-{g}"} for g in glosses],
        "cc_cedict_version": "v",
        "llm_model": "m",
        "prompt_version": "p",
        "generation_date": "2025-01-01T00:00:00+00:00",
    }


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_triggers_on_source_data():
    on = workflow()[True]  # YAML parses unquoted `on` as boolean True
    paths = on["push"]["paths"]
    for watched in (
        "data/cfdict.u8",
        "data/human.u8",
        "data/llm_generated.json",
    ):
        assert watched in paths, watched
    assert on["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in on


def test_workflow_has_test_then_release_jobs():
    jobs = workflow()["jobs"]
    assert set(jobs) == {"test", "assemble"}
    assert jobs["assemble"]["needs"] == ["test"]
    steps = " ".join(
        str(step) for step in jobs["assemble"]["steps"]
    )
    for stage in ("validate", "ssemble", "cope", "release"):
        assert stage in steps, stage


def test_workflow_requests_only_release_permissions():
    assert workflow()["permissions"] == {"contents": "write"}


def test_actions_are_pinned_to_major_versions():
    # Floating refs (@main) break reproducibility; every third-party step
    # must pin a major tag or SHA. The tags themselves are verified against
    # the GitHub API before sanctioning (no Docker here, so `act` cannot
    # run — see docs/workflow.md).
    import re

    uses = []

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "uses":
                    uses.append(value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(workflow())
    assert uses, "no actions referenced?!"
    for ref in uses:
        assert re.fullmatch(r"[^@\s]+@(v\d+|[0-9a-f]{40})", ref), ref


def run(*args, cwd):
    import os

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


@pytest.fixture()
def pipeline_data(tmp_path):
    (tmp_path / "cfdict.u8").write_text(BASE_SAMPLE, encoding="utf-8")
    (tmp_path / "cc.u8").write_text(CC_SAMPLE, encoding="utf-8")
    (tmp_path / "human.u8").write_text(HUMAN_SAMPLE, encoding="utf-8")
    (tmp_path / "llm_generated.json").write_text(
        json.dumps(
            {"行|行|Xing2": record_for("行|行|Xing2", ["to walk"])},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_pipeline_end_to_end(pipeline_data, tmp_path):
    d = pipeline_data
    out_c, out_f, scope = (
        tmp_path / "out_human.u8",
        tmp_path / "out_full.u8",
        tmp_path / "scope.md",
    )
    # 1. validate inputs
    r = run(
        "scripts/validate.py",
        "--cfdict", str(d / "cfdict.u8"),
        "--cc-cedict", str(d / "cc.u8"),
        "--human", str(d / "human.u8"),
        "--llm-generated", str(d / "llm_generated.json"),
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    # 2. assemble
    r = run(
        "scripts/assemble.py",
        "--cfdict", str(d / "cfdict.u8"),
        "--human", str(d / "human.u8"),
        "--llm-generated", str(d / "llm_generated.json"),
        "--out-human", str(out_c),
        "--out-full", str(out_f),
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    assert out_c.exists() and out_f.exists()
    # 3. validate outputs
    r = run(
        "scripts/validate.py",
        "--cfdict", str(d / "cfdict.u8"),
        "--cc-cedict", str(d / "cc.u8"),
        "--human", str(d / "human.u8"),
        "--llm-generated", str(d / "llm_generated.json"),
        "--out-human", str(out_c),
        "--out-full", str(out_f),
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    # 4. scope info
    r = run(
        "scripts/scope_info.py",
        "--cfdict", str(d / "cfdict.u8"),
        "--cc-cedict", str(d / "cc.u8"),
        "--human", str(d / "human.u8"),
        "--llm-generated", str(d / "llm_generated.json"),
        "--out", str(scope),
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr or r.stdout
    text = scope.read_text(encoding="utf-8")
    assert "Human dictionary: 2 entries" in text  # base + human
    assert "Full dictionary: 3 entries" in text  # + llm
    assert "Missing scope (still to generate): 1" in text  # 學 only
    # 5. assembled content is exactly what was validated
    assert "美 美 [Mei3] /beau/" in out_c.read_text(encoding="utf-8")
    assert "行 行 [Xing2] /fr-to walk/" in out_f.read_text(encoding="utf-8")
    assert "行 行" not in out_c.read_text(encoding="utf-8")


def test_pipeline_fails_fast_on_overlap(pipeline_data):
    d = pipeline_data
    (d / "llm_generated.json").write_text(
        json.dumps(
            {"中國|中国|Zhong1 guo2": record_for("中國|中国|Zhong1 guo2", ["China"])},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = run(
        "scripts/validate.py",
        "--cfdict", str(d / "cfdict.u8"),
        "--cc-cedict", str(d / "cc.u8"),
        "--human", str(d / "human.u8"),
        "--llm-generated", str(d / "llm_generated.json"),
        cwd=REPO,
    )
    assert r.returncode == 1
    assert "overlap" in (r.stdout + r.stderr).lower()
