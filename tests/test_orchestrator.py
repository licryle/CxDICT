"""Tests for the generation orchestrator (Phase 5.6, spec §3, §5, §8, §14).

All endpoint interaction is faked. Covers missing-scope planning,
batching, limit truncation, dry-run purity, atomicity on batch failure,
provenance stamping, and the CLI.
"""

import json

import pytest

from cfdict_next.generation.config import LLMConfig
from cfdict_next.generation.orchestrator import (
    compute_missing_items,
    generate_all,
    generate_files,
    plan_generation,
)
from cfdict_next.generation.llm import GenerationError
from cfdict_next.generation.output import Provenance
from cfdict_next.parser.u8 import DictionaryEntry


def entry(trad, simp, pin, defs):
    return DictionaryEntry(
        traditional=trad, simplified=simp, pinyin=pin, definitions=tuple(defs)
    )


def config(**overrides):
    args = {
        "endpoint": "http://test:1/x",
        "model": "m",
        "batch_size": 2,
        "max_retries": 0,
        "timeout_s": 5.0,
    }
    args.update(overrides)
    return LLMConfig(**args)


CC = [
    entry("中", "中", "Zhong1", ["middle"]),
    entry("國", "国", "Guo2", ["country", "state"]),
    entry("行", "行", "Xing2", ["to walk"]),
]

BASE_IDS = {"中|中|Zhong1"}  # 中 already authoritative


def test_missing_items_exclude_base_and_existing():
    items = compute_missing_items(CC, BASE_IDS, {"行|行|Xing2"})
    assert [i.key for i in items] == ["國|国|Guo2"]
    assert items[0].glosses == ("country", "state")


def test_missing_items_follow_cc_order_and_dedupe():
    items = compute_missing_items(CC + CC, set(), set())
    assert [i.key for i in items] == ["中|中|Zhong1", "國|国|Guo2", "行|行|Xing2"]


def test_plan_counts_batches():
    items = compute_missing_items(CC, set(), set())
    plan = plan_generation(items, batch_size=2, limit=0)
    assert (plan.scoped, plan.limited_to, plan.batches) == (3, 3, 2)
    plan = plan_generation(items, batch_size=2, limit=2)
    assert (plan.scoped, plan.limited_to, plan.batches) == (3, 2, 1)
    plan = plan_generation([], batch_size=2, limit=0)
    assert (plan.scoped, plan.limited_to, plan.batches) == (0, 0, 0)


def fake_post_factory(calls):
    def fake_post(endpoint, model, system, user, timeout_s):
        calls.append(user)
        import json as _json
        import re

        # Answer every requested id with a single-gloss sense set:
        # parse ids + glosses back out of the rendered user message.
        ids = [int(m) for m in re.findall(r"^\[(\d+)\]", user, re.M)]
        current, objects = None, []
        for line in user.splitlines():
            m = re.match(r"^\[(\d+)\] (\S+)", line)
            if m:
                current = {"id": int(m[1]), "word": m[2], "senses": []}
                objects.append(current)
            g = re.match(r'^\s+-\s+"(.*)"$', line)
            if g and current is not None:
                current["senses"].append({"gloss": g[1], "definition": f"fr-{g[1]}"})
        assert sorted(o["id"] for o in objects) == sorted(ids)
        return {"choices": [{"message": {"content": _json.dumps(objects)}}]}

    return fake_post


def test_generate_all_batches_and_groups():
    items = compute_missing_items(CC, set(), set())
    calls = []
    records, failed, _causes = generate_all(
        items,
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=fake_post_factory(calls),
    )
    assert failed == ()
    assert len(calls) == 2  # 3 items, batch_size 2
    assert set(records) == {"中|中|Zhong1", "國|国|Guo2", "行|行|Xing2"}
    assert [s["source_gloss"] for s in records["國|国|Guo2"]["senses"]] == [
        "country",
        "state",
    ]


def write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def dataset_files(tmp_path, base_ids_extra=frozenset()):
    base = write(tmp_path / "cfdict.u8", "中 中 [Zhong1] /milieu/\n")
    cc = write(
        tmp_path / "cc.u8",
        "中 中 [Zhong1] /middle/\n"
        "國 国 [Guo2] /country/\n"
        "行 行 [Xing2] /to walk/\n",
    )
    human_p = write(tmp_path / "human.u8", "")
    llm_p = write(tmp_path / "llm_generated.json", json.dumps({}))
    return base, cc, human_p, llm_p


def test_generate_files_end_to_end(tmp_path):
    base, cc, human_p, llm_p = dataset_files(tmp_path)
    calls = []
    report = generate_files(
        base, cc, human_p, llm_p,
        config(), "cc-v1", limit=0, post=fake_post_factory(calls),
        generation_date="T",
        language="fr",
    )
    assert report.plan.scoped == 2  # 國 + 行 (中 is base)
    assert report.llm_new == 2
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"國|国|Guo2", "行|行|Xing2"}
    assert llm_generated["國|国|Guo2"]["cc_cedict_version"] == "cc-v1"
    assert llm_generated["國|国|Guo2"]["llm_model"] == "m"


def test_limit_truncates_and_resumes(tmp_path):
    base, cc, human_p, llm_p = dataset_files(tmp_path)
    calls = []
    post = fake_post_factory(calls)
    first = generate_files(
        base, cc, human_p, llm_p, config(), "v", limit=1, post=post,
        generation_date="T",
        language="fr",
    )
    assert first.plan.limited_to == 1 and first.llm_new == 1
    second = generate_files(
        base, cc, human_p, llm_p, config(), "v", limit=0, post=post,
        generation_date="T",
        language="fr",
    )
    assert second.llm_new == 1  # only the remaining entry
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"國|国|Guo2", "行|行|Xing2"}


def test_dry_run_calls_no_batches_and_writes_nothing(tmp_path):
    base, cc, human_p, llm_p = dataset_files(tmp_path)
    before = (human_p.read_bytes(), llm_p.read_bytes())
    calls = []
    report = generate_files(
        base, cc, human_p, llm_p, config(), "v", dry_run=True,
        post=fake_post_factory(calls), language="fr",
    )
    assert calls == []
    assert report.dry_run and report.plan.scoped == 2
    assert (human_p.read_bytes(), llm_p.read_bytes()) == before


def test_total_failure_writes_nothing_and_raises(tmp_path):
    base, cc, human_p, llm_p = dataset_files(tmp_path)

    def bad_post(*args):
        raise GenerationError("boom")

    with pytest.raises(GenerationError, match="2 entries failed after retry") as exc_info:
        generate_files(
            base, cc, human_p, llm_p, config(), "v", limit=0, post=bad_post,
            language="fr",
        )
    assert "Causes:" in str(exc_info.value) and "boom" in str(exc_info.value)
    assert json.loads(llm_p.read_text(encoding="utf-8")) == {}


def test_poison_entry_isolated_rest_written_and_reported(tmp_path):
    # 國 always fails, even alone: its batch-mate 行 must still be written,
    # and the error must name the poison key for resume.
    base, cc, human_p, llm_p = dataset_files(tmp_path)
    good_post = fake_post_factory([])

    def flaky_post(endpoint, model, system, user, timeout_s):
        if "国" in user:  # simplified form of 國, poison in every attempt
            raise GenerationError("poison")
        return good_post(endpoint, model, system, user, timeout_s)

    with pytest.raises(GenerationError, match="國\\|国\\|Guo2"):
        generate_files(
            base, cc, human_p, llm_p, config(), "v", limit=0,
            post=flaky_post, generation_date="T", language="fr",
        )
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"行|行|Xing2"}  # success persisted
    # Resume skips the written entry and fails again only on the poison one.
    with pytest.raises(GenerationError, match="國\\|国\\|Guo2"):
        generate_files(
            base, cc, human_p, llm_p, config(), "v", limit=0,
            post=flaky_post, generation_date="T", language="fr",
        )
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"行|行|Xing2"}


def test_transient_failure_recovers_in_retry_pass(tmp_path):
    base, cc, human_p, llm_p = dataset_files(tmp_path)
    calls = []
    good_post = fake_post_factory(calls)
    state = {"failed_once": False}

    def transient_post(*args):
        if not state["failed_once"]:
            state["failed_once"] = True
            raise GenerationError("blip")
        return good_post(*args)

    report = generate_files(
        base, cc, human_p, llm_p, config(), "v", limit=0,
        post=transient_post, generation_date="T", language="fr",
    )
    assert report.llm_new == 2
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"國|国|Guo2", "行|行|Xing2"}


def test_progress_lines_report_counts_percent_and_elapsed():
    import io
    import re

    items = compute_missing_items(CC, set(), set())
    stream = io.StringIO()
    records, failed, _causes = generate_all(
        items,
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=fake_post_factory([]),
        stream=stream,
    )
    assert failed == ()
    lines = stream.getvalue().splitlines()
    assert len(lines) == 2  # 3 items, batch_size 2
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 1/2 succeeded: 2 processed / 0 errors / "
        r"1 to process / 3 total, 67% in \d{2}:\d{2}:\d{2}",
        lines[0],
    )
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 2/2 succeeded: 3 processed / 0 errors / "
        r"0 to process / 3 total, 100% in \d{2}:\d{2}:\d{2}",
        lines[1],
    )
    assert "\033[" not in stream.getvalue()  # StringIO is not a tty


def test_progress_colors_only_on_tty_without_no_color(monkeypatch):
    import io

    class TtyStream(io.StringIO):
        def isatty(self):
            return True

    def run(stream):
        generate_all(
            compute_missing_items(CC, set(), set()),
            config(),
            Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
            generation_date="T",
        language="fr",
            post=fake_post_factory([]),
            stream=stream,
        )
        return stream.getvalue()

    out = run(TtyStream())
    assert "\033[32m2 processed\033[0m" in out
    assert "\033[31m0 errors\033[0m" in out
    assert "\033[34m1 to process\033[0m / 3 total" in out
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033[" not in run(TtyStream())


def test_progress_marks_failed_batches_and_retries():
    import io
    import re

    good_post = fake_post_factory([])

    def poison_post(endpoint, model, system, user, timeout_s):
        if re.search(r"^\[\d+\] 行 \(", user, re.M):
            raise GenerationError("poison")
        return good_post(endpoint, model, system, user, timeout_s)

    stream = io.StringIO()
    records, failed, _causes = generate_all(
        compute_missing_items(CC, set(), set()),
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=poison_post,
        stream=stream,
    )
    assert failed == ("行|行|Xing2",)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 1/2 succeeded: 2 processed / 0 errors / "
        r"1 to process / 3 total, 67% in \d{2}:\d{2}:\d{2}",
        lines[0],
    )
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 2/2 FAILED: 2 processed / 1 errors / "
        r"0 to process / 3 total, 100% in \d{2}:\d{2}:\d{2} — "
        r"batch failed after 1 attempt\(s\): poison",
        lines[1],
    )
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Retry 1/1 FAILED: 2 processed / 1 errors / "
        r"0 to process / 3 total, 100% in \d{2}:\d{2}:\d{2} — "
        r"batch failed after 1 attempt\(s\): poison",
        lines[2],
    )


def test_retry_success_moves_entry_from_errors_to_done():
    import io
    import re

    good_post = fake_post_factory([])

    def batch_only_post(endpoint, model, system, user, timeout_s):
        import re

        ids = re.findall(r"^\[\d+\]", user, re.M)
        if len(ids) > 1:  # multi-entry batches always fail; singles recover
            raise GenerationError("batch too big")
        return good_post(endpoint, model, system, user, timeout_s)

    stream = io.StringIO()
    items = compute_missing_items(CC, set(), set())[:2]
    records, failed, _causes = generate_all(
        items,
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=batch_only_post,
        stream=stream,
    )
    assert failed == ()
    assert set(records) == {"中|中|Zhong1", "國|国|Guo2"}
    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 1/1 FAILED: 0 processed / 2 errors / "
        r"0 to process / 2 total, 100% in \d{2}:\d{2}:\d{2} — "
        r"batch failed after 1 attempt\(s\): batch too big",
        lines[0],
    )
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Retry 1/2 succeeded: 1 processed / 1 errors / "
        r"0 to process / 2 total, 100% in \d{2}:\d{2}:\d{2}",
        lines[1],
    )
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Retry 2/2 succeeded: 2 processed / 0 errors / "
        r"0 to process / 2 total, 100% in \d{2}:\d{2}:\d{2}",
        lines[2],
    )


def test_failed_lines_carry_truncated_single_line_cause():
    import io

    long_msg = "first line\nsecond line " + "x" * 500

    def bad_post(*args):
        raise GenerationError(long_msg)

    stream = io.StringIO()
    generate_all(
        compute_missing_items(CC, set(), set())[:1],
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=bad_post,
        stream=stream,
    )
    import re

    line = stream.getvalue().splitlines()[0]
    assert re.fullmatch(
        r"\[\d{2}:\d{2}:\d{2}] Batch 1/1 FAILED: 0 processed / 1 errors / "
        r"0 to process / 1 total, 100% in \d{2}:\d{2}:\d{2} — "
        r"batch failed after 1 attempt\(s\): first line second line x+…",
        line,
    )
    assert "\n" not in line and len(line) < 300


def test_partial_batch_writes_good_and_defers_bad(tmp_path):
    # The user's live case: one bogus entry beside a good one. The good
    # entry is written from the partial batch itself (no replay), only the
    # bogus one goes to single retry and names itself in the final error.
    import io

    base, cc, human_p, llm_p = dataset_files(tmp_path)

    def partial_post(endpoint, model, system, user, timeout_s):
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
            if g and current is not None and current["word"] != "国":
                current["senses"].append({"gloss": g[1], "definition": f"fr-{g[1]}"})
        return {"choices": [{"message": {"content": _json.dumps(objects)}}]}

    stream = io.StringIO()
    with pytest.raises(GenerationError, match="國\\|国\\|Guo2"):
        generate_files(
            base, cc, human_p, llm_p, config(), "v", limit=0,
            post=partial_post, generation_date="T", language="fr", stream=stream,
        )
    llm_generated = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(llm_generated) == {"行|行|Xing2"}
    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert (
        "Batch 1/1 PARTIAL: 1 processed / 1 errors / 0 to process / "
        "2 total, 100% in " in lines[0]
    )
    assert lines[0].endswith(
        "1 deferred, e.g. 國|国|Guo2: "
        "LLM response id 0: 'senses' must be a non-empty array"
    )
    assert (
        "Retry 1/1 FAILED: 1 processed / 1 errors / 0 to process / "
        "2 total, 100% in " in lines[1]
    )


def test_no_progress_prints_nothing():
    import io

    stream = io.StringIO()
    generate_all(
        compute_missing_items(CC, set(), set()),
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=fake_post_factory([]),
        progress=False,
        stream=stream,
    )
    assert stream.getvalue() == ""


def test_on_batch_fires_per_successful_batch():
    items = compute_missing_items(CC, set(), set())
    seen = []
    records, failed, _causes = generate_all(
        items,
        config(),
        Provenance(cc_cedict_version="v", llm_model="m", prompt_version="v"),
        generation_date="T",
        language="fr",
        post=fake_post_factory([]),
        on_batch=lambda rec: seen.append(set(rec)),
    )
    assert failed == ()
    assert len(seen) == 2  # batch_size 2 over 3 items
    assert seen[0] == {"中|中|Zhong1", "國|国|Guo2"}
    assert seen[1] == {"行|行|Xing2"}


def test_cli_reports_generation_error_without_traceback(tmp_path, capsys, monkeypatch):
    import cfdict_next.cli.generate as cli_mod
    from cfdict_next.cli.generate import main as cli_main

    base, cc, human_p, llm_p = dataset_files(tmp_path)
    env = tmp_path / ".env"
    env.write_text(
        "LLM_API_ENDPOINT=http://x:1/y\nLLM_MODEL_NAME=m\n", encoding="utf-8"
    )

    def failing_generate(*args, **kwargs):
        raise GenerationError("poison entry")

    monkeypatch.setattr(cli_mod, "generate_files", failing_generate)
    rc = cli_main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p)]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "generate failed" in err and "poison" in err


def test_cli_dry_run(tmp_path, capsys):
    from cfdict_next.cli.generate import main as cli_main

    base, cc, human_p, llm_p = dataset_files(tmp_path)
    env = tmp_path / ".env"
    env.write_text(
        "LLM_API_ENDPOINT=http://x:1/y\nLLM_MODEL_NAME=m\n", encoding="utf-8"
    )
    rc = cli_main(
        ["--env", str(env), "--language", "fr", "--base", str(base), "--cc-cedict", str(cc),
         "--human", str(human_p), "--llm-generated", str(llm_p),
         "--dry-run"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "2 entries in missing scope" in out


def test_cli_requires_language(tmp_path):
    from cfdict_next.cli.generate import main as cli_main

    with pytest.raises(SystemExit):
        cli_main(["--env", str(tmp_path / ".env")])
    with pytest.raises(SystemExit):
        cli_main(["--env", str(tmp_path / ".env"), "--language", "xx-unknown"])


def test_prompt_version_comes_from_registry(tmp_path):
    import json

    base, cc, human_p, llm_p = dataset_files(tmp_path)
    calls = []
    report = generate_files(
        base, cc, human_p, llm_p, config(), "v", limit=1,
        post=fake_post_factory(calls), generation_date="T", language="fr",
    )
    assert report.llm_new == 1
    records = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(records) == {"國|国|Guo2"}
    assert records["國|国|Guo2"]["prompt_version"] == "v6"


def test_hsk3_generates_without_base(tmp_path):
    import json

    _base, cc, human_p, llm_p = dataset_files(tmp_path)
    calls = []
    report = generate_files(
        None, cc, human_p, llm_p, config(), "v", limit=1,
        post=fake_post_factory(calls), generation_date="T",
        language="zh-CN-HSK03",
    )
    assert report.plan.scoped == 3  # no base: whole CC sample is missing scope
    assert report.llm_new == 1
    records = json.loads(llm_p.read_text(encoding="utf-8"))
    assert set(records) == {"中|中|Zhong1"}
    assert records["中|中|Zhong1"]["prompt_version"] == "v1"
    assert "HSK 3" in calls[0]  # HSK3 user-message voice, not the French one


def test_none_base_dry_run_plans_whole_scope(tmp_path):
    _base, cc, human_p, llm_p = dataset_files(tmp_path)
    report = generate_files(
        None, cc, human_p, llm_p, config(), "v", dry_run=True,
        language="zh-CN-HSK03",
    )
    assert report.plan.scoped == 3 and report.llm_new == 0
