"""Tests for the local end-to-end pipeline (spec §13 workflow, locally).

Fake endpoint throughout. Covers the full run, dry-run purity,
fail-fast stage attribution, and --skip-generate.
"""

import json

import pytest

from cxdict.cli.pipeline import PipelineError, main, run_pipeline
from cxdict.generation.config import LLMConfig


def config(**overrides):
    args = {
        "endpoint": "http://test:1/x",
        "model": "m",
        "batch_size": 10,
        "max_retries": 0,
        "timeout_s": 5.0,
    }
    args.update(overrides)
    return LLMConfig(**args)


BASE_SAMPLE = "中國 中国 [Zhong1 guo2] /Chine/\n"
CC_SAMPLE = (
    "中國 中国 [Zhong1 guo2] /China/Middle Kingdom/\n"
    "美 美 [Mei3] /beautiful/\n"
    "行 行 [Xing2] /to walk/\n"
)


def write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def fixture(tmp_path, human="", llm_generated=None):
    base = write(tmp_path / "cfdict.u8", BASE_SAMPLE)
    cc = write(tmp_path / "cc.u8", CC_SAMPLE)
    human_p = write(tmp_path / "human.u8", human)
    llm_p = write(
        tmp_path / "llm_generated.json",
        json.dumps(llm_generated if llm_generated is not None else {}, ensure_ascii=False),
    )
    return base, cc, human_p, llm_p


def fake_post(endpoint, model, system, user, timeout_s, api_key=None):
    import json as _json
    import re

    objects = []
    current = None
    for line in user.splitlines():
        m = re.match(r"^\[(\d+)\] (\S+)", line)
        if m:
            current = {"id": int(m[1]), "word": m[2], "senses": []}
            objects.append(current)
        g = re.match(r'^\s+-\s+"(.*)"$', line)
        if g and current is not None:
            current["senses"].append({"gloss": g[1], "definition": f"fr-{g[1]}"})
    return {"choices": [{"message": {"content": _json.dumps(objects)}}]}


def base_kwargs(tmp_paths, **overrides):
    base, cc, human_p, llm_p = tmp_paths
    args = {
        "base_path": base,
        "language": "fr",
        "cc_cedict_path": cc,
        "human_path": human_p,
        "llm_generated_path": llm_p,
        "out_human_path": tmp_paths[0].parent / "c.u8",
        "out_full_path": tmp_paths[0].parent / "f.u8",
        "config": config(),
        "cc_version": "cc-test",
        "limit": 0,
        "post": fake_post,
        "generation_date": "T",
    }
    args.update(overrides)
    return args


def test_cli_requires_language():
    import pytest

    from cxdict.cli.pipeline import main as cli_main

    with pytest.raises(SystemExit):
        cli_main(["--dry-run"])
    assert cli_main(["--language", "xx-unknown", "--dry-run"]) == 1


def test_full_run_end_to_end(tmp_path):
    paths = fixture(tmp_path)
    out_scope = tmp_path / "scope.md"
    report = run_pipeline(**base_kwargs(paths, scope_out=out_scope))
    assert not report.dry_run
    assert report.missing_scoped == 2  # 美 + 行 (中國 is base)
    assert report.generated == 2
    assert report.llm_new == 2
    assert report.human_n == 1 and report.full_n == 3
    assert (tmp_path / "c.u8").exists() and (tmp_path / "f.u8").exists()
    text = out_scope.read_text(encoding="utf-8")
    assert "| CxDICT-French-Human | 1 | 1 (33.3%) | 0 |" in text
    llm_generated = json.loads((tmp_path / "llm_generated.json").read_text(encoding="utf-8"))
    assert set(llm_generated) == {"美|美|Mei3", "行|行|Xing2"}


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path):
    paths = fixture(tmp_path)
    before = (
        (tmp_path / "human.u8").read_bytes(),
        (tmp_path / "llm_generated.json").read_bytes(),
    )
    calls = []
    report = run_pipeline(
        **base_kwargs(paths, dry_run=True, post=lambda *a: calls.append(1) or fake_post(*a))
    )
    assert report.dry_run and calls == []
    assert report.missing_scoped == 2
    assert (tmp_path / "llm_generated.json").read_bytes() == before[1]
    assert not (tmp_path / "c.u8").exists()  # no assembly in dry-run


def test_validation_failure_stops_before_assembly(tmp_path):
    bad_llm = {
        "美|美|Mei3": {
            "traditional": "美", "simplified": "美", "pinyin": "Mei3",
            "senses": [{"source_gloss": "pretty", "definition": "joli"}],
            "cc_cedict_version": "v",
            "llm_model": "m", "prompt_version": "p",
            "generation_date": "2025-01-01T00:00:00+00:00",
        }
    }
    paths = fixture(tmp_path, llm_generated=bad_llm)
    with pytest.raises(PipelineError, match=r"\[validate-inputs\]"):
        run_pipeline(**base_kwargs(paths, skip_generate=True))
    assert not (tmp_path / "c.u8").exists()


def test_skip_generate_uses_current_datasets(tmp_path):
    calls = []
    paths = fixture(tmp_path)
    report = run_pipeline(
        **base_kwargs(paths, skip_generate=True,
                      post=lambda *a: calls.append(1) or fake_post(*a))
    )
    assert calls == []
    assert report.generated == 0 and report.missing_scoped == 0
    assert report.human_n == 1 and report.full_n == 1  # base only


def test_stage_announcements_name_each_stage(tmp_path, capsys):
    paths = fixture(tmp_path)
    report = run_pipeline(**base_kwargs(paths, scope_out=tmp_path / "scope.md"))
    assert not report.dry_run
    out = capsys.readouterr().out
    assert "[generate] start: will process 2 of 2 missing entries in 1 batch" in out
    assert "[generate] done: 2 generated" in out
    assert "[cleanup] start" in out and "[cleanup] done: dropped 0" in out
    assert "[validate-inputs] start" in out and "[validate-inputs] done: " in out
    assert "[assemble] start" in out and "[assemble] done: 1 human, 3 full" in out
    assert "[validate-outputs] start" in out and "[validate-outputs] done" in out
    assert "[scope] start" in out and "[scope] done: wrote " in out


def test_skip_generate_announces_skip(tmp_path, capsys):
    paths = fixture(tmp_path)
    run_pipeline(**base_kwargs(paths, skip_generate=True))
    out = capsys.readouterr().out
    assert "[generate] skipped (--skip-generate)" in out
    assert "[generate] start" not in out


def test_no_progress_silences_stages_and_batches(tmp_path, capsys):
    paths = fixture(tmp_path)
    run_pipeline(**base_kwargs(paths, progress=False))
    assert capsys.readouterr().out == ""


def test_cli_dry_run(tmp_path, capsys):
    base, cc, human_p, llm_p = fixture(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LLM_API_ENDPOINT=http://x:1/y\nLLM_MODEL_NAME=m\n", encoding="utf-8")
    rc = main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p),
         "--out-human", str(tmp_path / "c.u8"),
         "--out-full", str(tmp_path / "f.u8"),
         "--scope-out", str(tmp_path / "scope.md"), "--dry-run"]
    )
    assert rc == 0
    assert "dry run" in capsys.readouterr().out


def test_cli_limit_defaults_to_unlimited(tmp_path, monkeypatch):
    import cxdict.cli.pipeline as pipeline_mod
    from cxdict.cli.pipeline import PipelineReport

    base, cc, human_p, llm_p = fixture(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LLM_API_ENDPOINT=http://x:1/y\nLLM_MODEL_NAME=m\n", encoding="utf-8")
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return PipelineReport(
            dry_run=True, missing_scoped=0, generated=0, llm_new=0,
            cleanup=None, human_n=0, full_n=0, scope_markdown="",
        )

    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run)
    rc = main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p),
         "--out-human", str(tmp_path / "c.u8"),
         "--out-full", str(tmp_path / "f.u8"),
         "--scope-out", str(tmp_path / "scope.md"), "--dry-run"]
    )
    assert rc == 0
    assert seen["limit"] == 0
    assert seen["progress"] is True
    rc = main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p),
         "--out-human", str(tmp_path / "c.u8"),
         "--out-full", str(tmp_path / "f.u8"),
         "--scope-out", str(tmp_path / "scope.md"), "--dry-run",
         "--no-progress"]
    )
    assert rc == 0
    assert seen["progress"] is False


def test_cli_reports_generation_error_with_stage(tmp_path, capsys, monkeypatch):
    import cxdict.cli.pipeline as pipeline_mod

    base, cc, human_p, llm_p = fixture(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LLM_API_ENDPOINT=http://x:1/y\nLLM_MODEL_NAME=m\n", encoding="utf-8")

    def failing_run(**kwargs):
        raise pipeline_mod.PipelineError("generate", "1 entry failed after retry")

    monkeypatch.setattr(pipeline_mod, "run_pipeline", failing_run)
    rc = main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p),
         "--out-human", str(tmp_path / "c.u8"),
         "--out-full", str(tmp_path / "f.u8"),
         "--scope-out", str(tmp_path / "scope.md")]
    )
    assert rc == 1
    assert "[generate]" in capsys.readouterr().out
