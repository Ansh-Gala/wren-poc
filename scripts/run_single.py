"""Run one question and show the whole pipeline.

    python scripts/run_single.py "Which workflow has the most tasks?"
    python scripts/run_single.py R03 --config D --privacy strict

Accepts either a question id from benchmark/questions.yaml (then the answer is
compared against ground truth) or free text (no comparison possible).

This is the mode that matters for studying Wren: it shows which MCP tools
Claude actually called, the SQL that came back, and where the answer diverged.
"""

from __future__ import annotations

import argparse
import textwrap

import _bootstrap  # noqa: F401

from benchmark.models import Question
from benchmark.questions import load_questions
from benchmark.runner import run_question
from llm_api.cli_provider import claude_version
from config.logging import register_secrets
from config.settings import CONFIG_NAMES, PRIVACY_MODES, load_settings
from database.connection import run_readonly
from wren_setup.mcp_config import DISALLOWED_TOOLS


def rule(title: str) -> None:
    print(f"\n{title}")
    print("-" * max(len(title), 40))


def show_rows(summary: dict | None, limit: int = 10) -> None:
    if not summary:
        print("  (none)")
        return
    if summary.get("error"):
        print(f"  ERROR: {summary['error']}")
        return
    columns = summary.get("columns", [])
    rows = summary.get("rows", [])
    print(f"  columns: {', '.join(columns)}")
    print(f"  rows:    {summary.get('row_count', 0)}")
    for row in rows[:limit]:
        print("    " + " | ".join("NULL" if v is None else str(v) for v in row))
    if summary.get("row_count", 0) > limit:
        print(f"    ... {summary['row_count'] - limit} more")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="question text, or an id such as R03")
    parser.add_argument("--config", choices=list(CONFIG_NAMES), default=None)
    parser.add_argument("--privacy", choices=list(PRIVACY_MODES), default=None)
    parser.add_argument("--model", default=None, help="override CLAUDE_MODEL")
    parser.add_argument("--show-raw", action="store_true", help="print Claude's raw reply")
    args = parser.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())
    if args.model:
        settings = type(settings)(**{**settings.__dict__, "claude_model": args.model})

    config_name = (args.config or settings.benchmark_config).upper()
    privacy_mode = args.privacy or settings.benchmark_privacy_mode

    version = claude_version(settings.claude_command)
    if not version:
        print(f"ERROR: Claude Code CLI not found (looked for "
              f"'{settings.claude_command}'). Install it and run "
              f"`claude --version` to confirm.")
        return 1

    known = {q.id.upper(): q for q in load_questions()}
    if args.question.upper() in known:
        question = known[args.question.upper()]
        has_ground_truth = True
    else:
        question = Question(
            id="ADHOC", category="-", question=args.question,
            expected_sql="SELECT 1 WHERE false", ordered=False,
        )
        has_ground_truth = False

    print("=" * 64)
    print("QUESTION")
    print("=" * 64)
    print(textwrap.fill(question.question, 64))
    if question.interpretation:
        rule("INTENDED INTERPRETATION")
        print(textwrap.fill(" ".join(question.interpretation.split()), 64))

    rule("SETUP")
    print(f"  claude        {version}")
    print(f"  config        {config_name} ({settings.project_dir(config_name).name})")
    print(f"  privacy mode  {privacy_mode}")
    print(f"  wren launch   serve mcp --transport stdio"
          f"{' --no-connect' if privacy_mode == 'strict' else ''}")
    print(f"  denied tools  {', '.join(DISALLOWED_TOOLS)}")

    result = run_question(question, config_name, privacy_mode, settings)

    rule("CLAUDE")
    print(f"  {'SUCCESS' if result.cli_ok else 'FAILURE'}"
          f"   {result.claude_time_ms / 1000:.1f}s")
    if result.error and not result.cli_ok:
        print(f"  error: {result.error}")

    rule("WREN / MCP")
    if result.tools_used:
        print("  Tools used:")
        for tool in dict.fromkeys(result.tools_used):
            count = result.tools_used.count(tool)
            print(f"    {tool}" + (f"  x{count}" if count > 1 else ""))
    else:
        print("  No Wren MCP tools were called.")
        print("  Claude answered from the question alone -- the semantic layer")
        print("  contributed nothing to this answer.")
    if result.mcp_errors:
        print("  MCP tool errors:")
        for err in result.mcp_errors:
            print(f"    {err.splitlines()[0][:200]}")

    rule("GENERATED SQL")
    if result.generated_sql:
        print(f"  (extracted via '{result.parse_strategy}' strategy)")
        for line in result.generated_sql.splitlines():
            print(f"    {line}")
    else:
        print("  No SQL could be extracted from Claude's reply.")

    rule("SAFETY GATE")
    print(f"  {'PASSED - read-only' if result.sql_valid else 'REJECTED'}")

    rule("POSTGRES")
    if result.generated_sql and result.sql_valid:
        print(f"  Execution: {'SUCCESS' if result.execution_success else 'FAILED'}"
              f"   {result.sql_execution_time_ms:.0f}ms")
        if result.sqlstate:
            print(f"  SQLSTATE:  {result.sqlstate}")
    else:
        print("  Not executed.")

    rule("RESULT")
    show_rows(result.actual_result)

    if has_ground_truth:
        rule("EXPECTED")
        show_rows(result.expected_result)

        rule("MATCH")
        if result.result_match:
            print("  PASS")
        else:
            print(f"  FAIL  ({result.failure_category})")
            print(f"\n  Expected SQL:")
            for line in question.expected_sql.strip().splitlines():
                print(f"    {line}")
    else:
        rule("MATCH")
        print("  n/a - free-text question, no ground truth to compare against.")

    if args.show_raw:
        rule("RAW CLAUDE OUTPUT")
        print(textwrap.indent(result.raw_output or "(empty)", "  "))

    rule("TIMING")
    print(f"  claude    {result.claude_time_ms / 1000:>7.1f}s")
    print(f"  postgres  {result.sql_execution_time_ms / 1000:>7.2f}s")
    print(f"  total     {result.total_time_ms / 1000:>7.1f}s")
    print(f"  tokens    {result.prompt_tokens} in, {result.completion_tokens} out")

    return 0 if (result.result_match or not has_ground_truth) else 2


if __name__ == "__main__":
    import os
    import sys
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
