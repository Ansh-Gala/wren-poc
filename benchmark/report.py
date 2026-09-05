"""Benchmark reporting.

Every number is computed from the actual records. Nothing is estimated,
smoothed or carried over from a previous run.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from benchmark.classify import is_heuristic
from benchmark.models import QuestionResult

CSV_FIELDS = [
    "question_id", "category", "question", "config_name", "privacy_mode",
    "sql_valid", "execution_success", "result_match", "failure_category",
    "parse_strategy", "tools_used", "sqlstate", "timed_out", "cli_ok",
    "claude_time_ms", "sql_execution_time_ms", "total_time_ms",
    "prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens",
    "wren_tool_calls",
    "expected_sql", "generated_sql", "error",
]


def _pct(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator else 0.0


def summarize(results: list[QuestionResult]) -> dict:
    total = len(results)
    generated = sum(1 for r in results if r.generated_sql)
    executable = sum(1 for r in results if r.execution_success)
    matched = sum(1 for r in results if r.result_match)

    by_category: dict[str, dict] = {}
    grouped: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        grouped[r.category].append(r)
    for category, items in sorted(grouped.items()):
        n = len(items)
        by_category[category] = {
            "total": n,
            "sql_generated": sum(1 for r in items if r.generated_sql),
            "execution_success": sum(1 for r in items if r.execution_success),
            "result_match": sum(1 for r in items if r.result_match),
            "result_accuracy_pct": _pct(sum(1 for r in items if r.result_match), n),
        }

    failures = Counter(
        r.failure_category for r in results
        if not r.result_match and r.failure_category
    )
    tools = Counter(tool for r in results for tool in r.tools_used)

    durations = sorted(r.total_time_ms for r in results) or [0.0]

    prompts = [r.prompt_tokens for r in results if r.prompt_tokens]
    completions = [r.completion_tokens for r in results if r.completion_tokens]
    wren_calls = [r.wren_tool_calls for r in results]

    return {
        "prompt_tokens_avg": round(sum(prompts) / len(prompts)) if prompts else 0,
        "prompt_tokens_max": max(prompts) if prompts else 0,
        "prompt_tokens_total": sum(prompts),
        "completion_tokens_avg": round(sum(completions) / len(completions)) if completions else 0,
        "cache_read_tokens_total": sum(r.cache_read_tokens for r in results),
        "cache_write_tokens_total": sum(r.cache_write_tokens for r in results),
        "wren_tool_calls_avg": round(sum(wren_calls) / len(wren_calls), 2) if wren_calls else 0.0,
        "questions_without_wren": sum(1 for r in results if r.wren_tool_calls == 0),
        "total": total,
        "sql_generated": generated,
        "sql_executable": executable,
        "result_match": matched,
        "sql_generation_pct": _pct(generated, total),
        "execution_success_pct": _pct(executable, total),
        "result_accuracy_pct": _pct(matched, total),
        "by_category": by_category,
        "failure_categories": dict(failures.most_common()),
        "heuristic_failure_count": sum(
            n for cat, n in failures.items() if is_heuristic(cat)
        ),
        "tools_used": dict(tools.most_common()),
        "median_total_ms": durations[len(durations) // 2],
        "total_wall_ms": sum(r.total_time_ms for r in results),
        "total_cost_note": "see latest.json records for per-question timings",
        "configs": sorted({r.config_name for r in results if r.config_name}),
        "privacy_modes": sorted({r.privacy_mode for r in results if r.privacy_mode}),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _bar(pct: float, width: int = 24) -> str:
    filled = int(round(pct / 100 * width))
    return "#" * filled + "." * (width - filled)


def render_markdown(results: list[QuestionResult], summary: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Wren + Claude Code text-to-SQL benchmark")
    add("")
    add(f"Generated {summary['generated_at']}  ")
    add(f"Configuration(s): {', '.join(summary['configs']) or 'n/a'}  ")
    add(f"Privacy mode(s): {', '.join(summary['privacy_modes']) or 'n/a'}")
    add("")
    add("```")
    add("========================================")
    add("WREN + CLAUDE BENCHMARK")
    add("========================================")
    add("")
    add(f"Total questions:        {summary['total']}")
    add("")
    add(f"SQL generated:          {summary['sql_generated']} / {summary['total']}")
    add(f"SQL executable:         {summary['sql_executable']} / {summary['total']}")
    add(f"Correct results:        {summary['result_match']} / {summary['total']}")
    add("")
    add(f"SQL generation:         {summary['sql_generation_pct']:.2f}%")
    add(f"Execution success:      {summary['execution_success_pct']:.2f}%")
    add(f"Result accuracy:        {summary['result_accuracy_pct']:.2f}%")
    add("```")
    add("")

    add("## Accuracy by category")
    add("")
    add("| Category | Questions | SQL | Ran | Correct | Accuracy | |")
    add("|---|---:|---:|---:|---:|---:|---|")
    for category, stats in summary["by_category"].items():
        add(
            f"| {category} | {stats['total']} | {stats['sql_generated']} | "
            f"{stats['execution_success']} | {stats['result_match']} | "
            f"{stats['result_accuracy_pct']:.1f}% | `{_bar(stats['result_accuracy_pct'])}` |"
        )
    add("")

    if summary["failure_categories"]:
        add("## Failure categories")
        add("")
        add("| Category | Count | Basis |")
        add("|---|---:|---|")
        for category, count in summary["failure_categories"].items():
            basis = "heuristic" if is_heuristic(category) else "deterministic"
            add(f"| {category} | {count} | {basis} |")
        add("")
        add("**Deterministic** categories are read from facts: a process that timed "
            "out, a tool that returned an error, a gate that refused the statement, "
            "or a SQLSTATE PostgreSQL itself returned.")
        add("")
        add("**Heuristic** categories are inferred by diffing the generated SQL "
            "against the expected SQL. There are many correct ways to write a "
            "query, so a structural difference is not proof of the cause. Treat "
            "these as triage hints, not findings; `RESULT_MISMATCH` is the honest "
            "default when nothing else was confident.")
        add("")

    if summary["tools_used"]:
        add("## Wren MCP tools used")
        add("")
        add("| Tool | Calls |")
        add("|---|---:|")
        for tool, count in summary["tools_used"].items():
            add(f"| `{tool}` | {count} |")
        add("")

    failed = [r for r in results if not r.result_match]
    if failed:
        add("## Failures")
        add("")
        for r in failed:
            add(f"### {r.question_id} ({r.category}) - {r.failure_category}")
            add("")
            add(f"**Question:** {r.question}")
            add("")
            add("**Expected SQL**")
            add("")
            add("```sql")
            add((r.expected_sql or "-- no expected SQL (ambiguous/unanswerable)").strip())
            add("```")
            add("")
            add("**Generated SQL**")
            add("")
            add("```sql")
            add((r.generated_sql or "-- no SQL was produced").strip())
            add("```")
            add("")
            if r.error:
                add(f"**Error:** `{r.error.splitlines()[0][:300]}`")
                add("")
            if r.tools_used:
                add(f"**Wren tools called:** {', '.join(dict.fromkeys(r.tools_used))}")
                add("")

    add("## Reading these numbers")
    add("")
    add("- Agentic runs are not deterministic. The same question can pass in one "
        "run and fail in the next, so a single run's score carries real "
        "run-to-run variance. Repeat a run before treating a difference of a few "
        "points as meaningful.")
    add("- Result accuracy compares returned rows, never SQL text. Column order "
        "and aliases are ignored; row order is enforced only where the question "
        "asked for it.")
    add("- No database rows were sent to Claude. Generated SQL is executed here, "
        "and the results in this report never re-entered the model.")
    add("")

    return "\n".join(lines) + "\n"


def write_reports(results: list[QuestionResult], out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)

    (out_dir / "latest.json").write_text(
        json.dumps(
            {"summary": summary, "results": [asdict(r) for r in results]},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    with (out_dir / "latest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = asdict(r)
            row["tools_used"] = ";".join(row.get("tools_used") or [])
            writer.writerow(row)

    (out_dir / "latest.md").write_text(
        render_markdown(results, summary), encoding="utf-8"
    )
    return summary


def print_summary(summary: dict) -> None:
    print("=" * 40)
    print("WREN + CLAUDE BENCHMARK")
    print("=" * 40)
    print()
    print(f"Total questions:        {summary['total']}")
    print()
    print(f"SQL generated:          {summary['sql_generated']} / {summary['total']}")
    print(f"SQL executable:         {summary['sql_executable']} / {summary['total']}")
    print(f"Correct results:        {summary['result_match']} / {summary['total']}")
    print()
    print(f"SQL generation:         {summary['sql_generation_pct']:.2f}%")
    print(f"Execution success:      {summary['execution_success_pct']:.2f}%")
    print(f"Result accuracy:        {summary['result_accuracy_pct']:.2f}%")
    print()
    print(f"Prompt tokens avg:      {summary.get('prompt_tokens_avg', 0):,}")
    print(f"Prompt tokens max:      {summary.get('prompt_tokens_max', 0):,}")
    print(f"Completion tokens avg:  {summary.get('completion_tokens_avg', 0):,}")
    if summary.get("cache_read_tokens_total"):
        print(f"Cache read tokens:      {summary['cache_read_tokens_total']:,}")
        print(f"Cache write tokens:     {summary.get('cache_write_tokens_total', 0):,}")
    print(f"Wren calls per question:{summary.get('wren_tool_calls_avg', 0):>7}")
    if summary.get("questions_without_wren"):
        print(f"  !! {summary['questions_without_wren']} question(s) used no Wren tool at all")
    print()
    if summary["by_category"]:
        print("By category:")
        for category, stats in summary["by_category"].items():
            print(f"  {category}  {stats['result_match']:>3}/{stats['total']:<3} "
                  f"{stats['result_accuracy_pct']:>6.1f}%  {_bar(stats['result_accuracy_pct'])}")
        print()
    if summary["failure_categories"]:
        print("Failures:")
        for category, count in summary["failure_categories"].items():
            basis = "heuristic" if is_heuristic(category) else "deterministic"
            print(f"  {category:<28} {count:>3}  ({basis})")
        print()
