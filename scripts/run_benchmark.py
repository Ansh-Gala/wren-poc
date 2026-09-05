"""Run the benchmark.

    python scripts/run_benchmark.py                          # 86 questions, config D
    python scripts/run_benchmark.py --config A,B,C --subset 25
    python scripts/run_benchmark.py --categories R,S
    python scripts/run_benchmark.py --resume

Results are appended to results/raw/<config>.<privacy>.jsonl as each question
finishes, so a long run can be watched, stopped and resumed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from benchmark.questions import load_questions, select
from benchmark.report import print_summary, write_reports
from benchmark.runner import load_previous_results, run_benchmark
from llm_api.cli_provider import claude_version
from config.logging import get_logger, register_secrets
from config.settings import CONFIG_NAMES, PRIVACY_MODES, load_settings
from wren_setup.preflight import PreflightError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None,
                        help=f"comma-separated: {','.join(CONFIG_NAMES)} (default from .env)")
    parser.add_argument("--privacy", choices=list(PRIVACY_MODES), default=None)
    parser.add_argument("--subset", type=int, default=None,
                        help="stratified sample of N questions (reproducible)")
    parser.add_argument("--categories", default=None, help="e.g. R,S")
    parser.add_argument("--ids", default=None, help="e.g. A01,R06")
    parser.add_argument("--resume", action="store_true",
                        help="skip questions already recorded in the JSONL")
    parser.add_argument("--verbose", action="store_true",
                        help="live stream generated SQL and errors")
    parser.add_argument("--out", default="results", help="output directory")
    args = parser.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    log = get_logger("run_benchmark", settings.debug)

    version = claude_version(settings.claude_command)
    if not version:
        log.error("Claude Code CLI not found ('%s'). Install it and retry.",
                  settings.claude_command)
        return 1

    configs = [c.strip().upper() for c in (args.config or settings.benchmark_config).split(",")]
    for c in configs:
        if c not in CONFIG_NAMES:
            log.error("unknown config %r; expected one of %s", c, ", ".join(CONFIG_NAMES))
            return 1
    privacy_mode = args.privacy or settings.benchmark_privacy_mode

    all_questions = load_questions()
    questions = select(
        all_questions,
        categories=args.categories,
        subset=args.subset,
        ids=[i.strip() for i in args.ids.split(",")] if args.ids else None,
    )
    if not questions:
        log.error("no questions selected")
        return 1

    out_dir = Path(args.out)
    raw_dir = out_dir / "raw"
    every_result = []

    print(f"claude {version}")
    print(f"configs: {', '.join(configs)}   privacy: {privacy_mode}")
    print(f"questions: {len(questions)} of {len(all_questions)}")
    print(f"estimated: ~{len(questions) * len(configs) * 30 / 60:.0f} min "
          f"at ~30s per question\n")

    for config_name in configs:
        jsonl = raw_dir / f"{config_name}.{privacy_mode}.jsonl"
        skip_ids: set[str] = set()
        if args.resume:
            previous = load_previous_results(jsonl)
            skip_ids = {r.get("question_id") for r in previous if r.get("question_id")}
            if skip_ids:
                print(f"config {config_name}: resuming, skipping "
                      f"{len(skip_ids)} already-recorded question(s)")
        elif jsonl.exists():
            jsonl.unlink()

        def live_print(res):
            verdict = "PASS" if res.result_match else (res.failure_category or "FAIL")
            print(f"[{res.question_id}] {verdict} - {res.total_time_ms / 1000:.1f}s")
            if args.verbose:
                if res.generated_sql:
                    print(f"  SQL: {res.generated_sql.strip()}")
                if res.error:
                    print(f"  ERROR: {res.error}")
                print()

        try:
            results = run_benchmark(
                questions, config_name, privacy_mode, settings,
                jsonl_path=jsonl, skip_ids=skip_ids, on_result=live_print if args.verbose else None
            )
        except PreflightError as exc:
            log.error("config %s aborted: %s", config_name, exc)
            print("\nThe run stopped because the Wren semantic layer was not "
                  "actually in use. Nothing was measured. Fix the setup and "
                  "retry:\n  python scripts/check_environment.py")
            return 1

        every_result.extend(results)

        summary = write_reports(
            results, out_dir if len(configs) == 1 else out_dir / config_name
        )
        print(f"\n--- config {config_name} ---")
        print_summary(summary)

    if len(configs) > 1:
        summary = write_reports(every_result, out_dir)
        print("\n--- combined ---")
        print_summary(summary)

        print("Knowledge lift (result accuracy by configuration):")
        for config_name in configs:
            subset = [r for r in every_result if r.config_name == config_name]
            matched = sum(1 for r in subset if r.result_match)
            pct = matched / len(subset) * 100 if subset else 0.0
            print(f"  {config_name}  {matched:>3}/{len(subset):<3}  {pct:>6.2f}%")
        print()

    no_wren = [r for r in every_result if r.wren_tool_calls == 0]
    if no_wren:
        print(f"WARNING: {len(no_wren)} question(s) were answered without calling "
              f"any Wren MCP tool: {', '.join(r.question_id for r in no_wren)}")
        print("  For those, the score reflects Claude alone, not Claude + Wren.")

    print(f"Reports written to {out_dir}/latest.{{json,csv,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
