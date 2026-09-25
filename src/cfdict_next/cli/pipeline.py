"""Local end-to-end pipeline: generate → cleanup → validate → assemble.

Single entry point for a full local run over real sources. Each stage
uses the same library functions as the individual scripts (and therefore
the same code paths CI exercises step by step), failing fast with the
stage name on any violation.

Safety: --limit caps entries per run (default 0 = unlimited, unlike
scripts/generate.py whose default 20 stays capped); --dry-run plans
without endpoint calls or writes; --skip-generate re-runs only the
downstream stages over the current datasets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..assembly import assemble_files
from ..cleanup import CleanupReport, cleanup_files
from ..generation.config import LLMConfig
from ..generation.llm import GenerationError
from ..generation.orchestrator import generate_files
from ..generation.llm import post_chat_completions
from ..languages import LANGUAGES, get_language
from ..scope_info import (
    ReleaseSources,
    build_scope_info,
    collect_llm_provenance,
    render_scope_markdown,
    sha256_file,
)
from ..validation import ValidationReport, check_outputs, validate_inputs


class PipelineError(Exception):
    """A pipeline stage failed; `stage` names which one."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"[{stage}] {message}")
        self.stage = stage


@dataclass
class PipelineReport:
    """Outcome of a pipeline run."""

    dry_run: bool
    missing_scoped: int
    generated: int
    llm_new: int
    cleanup: CleanupReport | None
    human_n: int
    full_n: int
    scope_markdown: str


def _failures(report: ValidationReport) -> str:
    return "; ".join(
        f"{c.name}: {c.detail}" for c in report.failures()
    )


def run_pipeline(
    *,
    base_path: str | Path | None,
    cc_cedict_path: str | Path,
    human_path: str | Path,
    llm_generated_path: str | Path,
    out_human_path: str | Path,
    out_full_path: str | Path,
    config: LLMConfig,
    language: str,
    cc_version: str | None = None,
    limit: int = 0,
    dry_run: bool = False,
    skip_generate: bool = False,
    progress: bool = True,
    scope_out: str | Path | None = None,
    post: Callable[..., Any] = post_chat_completions,
    generation_date: str | None = None,
) -> PipelineReport:
    """Run the full local pipeline; raise PipelineError on any failure."""
    base_label = get_language(language).base_label
    # None base_path means the language has no authoritative base.
    base_path = Path(base_path) if base_path is not None else None
    cc_cedict_path = Path(cc_cedict_path)
    human_path, llm_generated_path = Path(human_path), Path(llm_generated_path)

    def _announce(text: str) -> None:
        if progress:
            print(text, flush=True)

    try:
        cc_version = cc_version or sha256_file(cc_cedict_path)
    except OSError as exc:
        raise PipelineError("setup", f"cannot hash CC-CEDICT: {exc}") from exc

    if skip_generate:
        gen_report = None
        _announce("[generate] skipped (--skip-generate)")
    else:
        # Read-only plan first so the start line can say what the run
        # will process; costs one extra parse, negligible next to LLM calls.
        try:
            pre = generate_files(
                base_path,
                cc_cedict_path,
                human_path,
                llm_generated_path,
                config,
                cc_version,
                limit=limit,
                dry_run=True,
                post=post,
                progress=False,
                language=language,
            )
        except (ValueError, OSError, GenerationError) as exc:
            raise PipelineError("generate", str(exc)) from exc
        _announce(
            f"[generate] start: will process {pre.plan.limited_to} of "
            f"{pre.plan.scoped} missing entries in {pre.plan.batches} batches"
        )
        if dry_run:
            gen_report = pre
        else:
            try:
                gen_report = generate_files(
                    base_path,
                    cc_cedict_path,
                    human_path,
                    llm_generated_path,
                    config,
                    cc_version,
                    limit=limit,
                    dry_run=False,
                    generation_date=generation_date,
                    post=post,
                    progress=progress,
                    language=language,
                )
            except (ValueError, OSError, GenerationError) as exc:
                raise PipelineError("generate", str(exc)) from exc
            _announce(f"[generate] done: {gen_report.llm_new} generated")

    if dry_run:
        # Read-only assessment of the current datasets; nothing downstream.
        report, _ = validate_inputs(
            base_path, cc_cedict_path, human_path, llm_generated_path
        )
        return PipelineReport(
            dry_run=True,
            missing_scoped=gen_report.plan.scoped if gen_report else 0,
            generated=0,
            llm_new=0,
            cleanup=None,
            human_n=0,
            full_n=0,
            scope_markdown="",
        )

    _announce("[cleanup] start")
    try:
        cleanup_report = cleanup_files(
            base_path, human_path, llm_generated_path
        )
    except (ValueError, OSError) as exc:
        raise PipelineError("cleanup", str(exc)) from exc
    dropped = (
        cleanup_report.human_removed_base
        + cleanup_report.llm_removed_base
        + cleanup_report.llm_removed_human
    )
    _announce(f"[cleanup] done: dropped {dropped}")

    _announce("[validate-inputs] start")
    report, data = validate_inputs(
        base_path, cc_cedict_path, human_path, llm_generated_path
    )
    if data is None or not report.passed:
        raise PipelineError("validate-inputs", _failures(report))
    _announce(
        f"[validate-inputs] done: {len(data['base_ids'])} base, "
        f"{len(data['human_ids'])} human, "
        f"{len(data['llm_generated'])} generated"
    )

    _announce("[assemble] start")
    try:
        human_n, full_n = assemble_files(
            base_path,
            human_path,
            llm_generated_path,
            out_human_path,
            out_full_path,
            language,
        )
    except (ValueError, OSError) as exc:
        raise PipelineError("assemble", str(exc)) from exc
    _announce(f"[assemble] done: {human_n} human, {full_n} full entries")

    _announce("[validate-outputs] start")
    out_report = ValidationReport()
    check_outputs(
        out_human_path,
        out_full_path,
        data["base_ids"],
        data["human_ids"],
        set(data["llm_generated"]),
        out_report,
    )
    if not out_report.passed:
        raise PipelineError("validate-outputs", _failures(out_report))
    _announce("[validate-outputs] done: outputs consistent")

    _announce("[scope] start")
    models, prompts = collect_llm_provenance(data["llm_generated"])
    try:
        base_version = sha256_file(base_path) if base_path is not None else ""
        human_version = sha256_file(human_path)
        llm_generated_version = sha256_file(llm_generated_path)
    except OSError as exc:
        raise PipelineError("scope", f"cannot hash sources: {exc}") from exc
    sources = ReleaseSources(
        cc_cedict_version=cc_version,
        cc_cedict_ids=set(data["cc_glosses"]),
        base_version=base_version,
        base_ids=data["base_ids"],
        human_version=human_version,
        human_ids=data["human_ids"],
        llm_generated_version=llm_generated_version,
        llm_generated_ids=set(data["llm_generated"]),
        llm_models=models,
        prompt_versions=prompts,
    )
    markdown = render_scope_markdown(build_scope_info(sources), base_label)
    if scope_out is not None:
        try:
            Path(scope_out).write_text(markdown, encoding="utf-8")
        except OSError as exc:
            raise PipelineError("scope", f"cannot write scope file: {exc}") from exc
        _announce(f"[scope] done: wrote {scope_out}")
    else:
        _announce("[scope] done")

    return PipelineReport(
        dry_run=False,
        missing_scoped=gen_report.plan.scoped if gen_report else 0,
        generated=gen_report.plan.limited_to if gen_report else 0,
        llm_new=gen_report.llm_new if gen_report else 0,
        cleanup=cleanup_report,
        human_n=human_n,
        full_n=full_n,
        scope_markdown=markdown,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: full local pipeline in one command."""
    import argparse
    import dataclasses

    from ..generation.config import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--language", required=True, choices=sorted(LANGUAGES),
                        help="target dictionary language")
    parser.add_argument("--base", default="data/cfdict.u8")
    parser.add_argument(
        "--cc-cedict", default="data/cc-cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
    )
    parser.add_argument("--human", default="data/human.u8")
    parser.add_argument("--llm-generated", default="data/llm_generated.json")
    parser.add_argument("--out-human", default="output/cfdict-next-human.u8")
    parser.add_argument("--out-full", default="output/cfdict-next-full.u8")
    parser.add_argument("--cc-version", default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--scope-out", default="scope.md")
    args = parser.parse_args(argv)

    if args.limit < 0:
        print("pipeline failed: --limit must be >= 0 (0 = unlimited)")
        return 1
    try:
        config = load_config(args.env)
    except (ValueError, OSError) as exc:
        print(f"pipeline failed: {exc}")
        return 1
    if args.batch_size is not None:
        if args.batch_size <= 0:
            print("pipeline failed: --batch-size must be positive")
            return 1
        config = dataclasses.replace(config, batch_size=args.batch_size)
    try:
        report = run_pipeline(
            base_path=args.base,
            cc_cedict_path=args.cc_cedict,
            human_path=args.human,
            llm_generated_path=args.llm_generated,
            out_human_path=args.out_human,
            out_full_path=args.out_full,
            config=config,
            language=args.language,
            cc_version=args.cc_version,
            limit=args.limit,
            dry_run=args.dry_run,
            skip_generate=args.skip_generate,
            progress=not args.no_progress,
            scope_out=None if args.dry_run else args.scope_out,
        )
    except PipelineError as exc:
        print(f"pipeline failed: {exc}")
        return 1
    if report.dry_run:
        print(
            "dry run — nothing called or written: "
            f"{report.missing_scoped} entries in missing scope"
        )
    else:
        dropped = 0
        if report.cleanup is not None:
            dropped = (
                report.cleanup.human_removed_base
                + report.cleanup.llm_removed_base
                + report.cleanup.llm_removed_human
            )
        print(
            f"pipeline done: generated {report.generated}/{report.missing_scoped} "
            f"({report.llm_new} generated), "
            f"cleanup dropped {dropped}, "
            f"dictionaries {report.human_n}/{report.full_n} entries"
        )
        if report.generated < report.missing_scoped:
            print(
                "scope truncated by --limit; re-run resumes the rest "
                "(already-written entries leave the missing scope)"
            )
    return 0
