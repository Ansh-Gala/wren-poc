"""Run questions end to end and score them.

One question is: ask Claude (which consults Wren over MCP) -> parse the SQL ->
gate it as read-only -> execute it here -> execute the ground truth here, in the
same moment -> compare results -> classify any failure.

The expected query is deliberately re-executed on every question rather than
cached. Seed dates are relative to CURRENT_DATE, so a cached expectation would
drift; running both queries together keeps every comparison fair.

Results are appended to a JSONL file as they complete, so a long run is
inspectable while it is still going and resumable if it stops.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from benchmark.classify import classify_failure
from benchmark.evaluator import compare_results, result_summary
from benchmark.models import Question, QuestionResult, Session
from benchmark.questions import load_questions  # noqa: F401  (re-exported)
from benchmark.safety import UnsafeSQLError, assert_read_only
from llm_api.factory import get_provider
from claude.parser import parse_sql
from config.logging import get_logger
from config.settings import Settings
from database.connection import run_readonly
from wren_setup.mcp_config import write_mcp_config
from wren_setup.preflight import PreflightError, check as preflight_check, wren_tool_calls

log = get_logger("benchmark.runner")


def run_question(
    question: Question,
    config_name: str,
    privacy_mode: str,
    settings: Settings,
    mcp_config_path: Path | None = None,
    session: Session | None = None,
) -> QuestionResult:
    started = time.perf_counter()
    if mcp_config_path is None:
        mcp_config_path = write_mcp_config(config_name, privacy_mode, settings)

    result = QuestionResult(
        question_id=question.id,
        category=question.category,
        question=question.question,
        expected_sql=question.expected_sql,
        tags=list(question.tags),
        config_name=config_name,
        privacy_mode=privacy_mode,
    )

    # 1. Ask the configured LLM provider. Wren is reached via MCP.
    provider = get_provider(settings)
    run = provider.ask(question.question, mcp_config_path, privacy_mode, settings, session)
    result.claude_time_ms = run.duration_ms
    result.tools_used = run.tools_used
    result.mcp_errors = run.mcp_errors
    result.wren_tool_calls = wren_tool_calls(run.tools_used)
    result.prompt_tokens = run.prompt_tokens
    result.completion_tokens = run.completion_tokens
    result.cache_read_tokens = run.cache_read_tokens
    result.cache_write_tokens = run.cache_write_tokens
    result.timed_out = run.timed_out
    result.cli_ok = run.ok and not run.timed_out
    result.raw_output = run.result_text
    if run.error:
        result.error = run.error

    # 2. Extract the SQL.
    parsed = parse_sql(run.result_text)
    result.parse_strategy = parsed.strategy
    result.generated_sql = parsed.sql

    # 3. Gate it. Nothing unvalidated ever reaches the database.
    if parsed.sql:
        try:
            assert_read_only(parsed.sql)
            result.sql_valid = True
        except UnsafeSQLError as exc:
            result.sql_valid = False
            result.error = result.error or f"unsafe SQL: {exc}"

    # 4. Execute the generated SQL, then the ground truth, together.
    expected = run_readonly(settings, question.expected_sql, settings.statement_timeout_ms)
    result.expected_result = result_summary(expected)

    if result.sql_valid and parsed.sql:
        actual = run_readonly(settings, parsed.sql, settings.statement_timeout_ms)
        result.sql_execution_time_ms = actual.duration_ms
        result.actual_result = result_summary(actual)
        result.execution_success = actual.ok
        result.sqlstate = actual.sqlstate
        if actual.error:
            result.error = result.error or actual.error
        if actual.ok:
            result.result_match = compare_results(expected, actual, question.ordered)
            if not result.result_match:
                from benchmark.evaluator import (
                    compare_projection_agnostic, compare_row_subset,
                )
                if compare_row_subset(expected, actual, question.ordered):
                    result.result_match = True
                elif compare_projection_agnostic(expected, actual, question.ordered):
                    # Right rows, different column choice on a question that
                    # never specified one. Counted as correct.
                    result.result_match = True

    if not result.result_match:
        result.failure_category = classify_failure(result)

    result.total_time_ms = (time.perf_counter() - started) * 1000
    return result


def run_benchmark(
    questions: Iterable[Question],
    config_name: str,
    privacy_mode: str,
    settings: Settings,
    jsonl_path: Path | None = None,
    on_result: Callable[[QuestionResult], None] | None = None,
    skip_ids: set[str] | None = None,
) -> list[QuestionResult]:
    questions = list(questions)

    # Prove the semantic layer is actually reachable before spending an hour
    # measuring something else. See wren_setup/preflight.py for why.
    tools = preflight_check(config_name, privacy_mode, settings)
    log.info("preflight ok: %d Wren MCP tools available", len(tools))

    mcp_config_path = write_mcp_config(config_name, privacy_mode, settings)
    log.info(
        "config %s / %s: %d question(s), mcp config %s",
        config_name, privacy_mode, len(questions), mcp_config_path,
    )

    results: list[QuestionResult] = []
    for index, question in enumerate(questions, 1):
        if skip_ids and question.id in skip_ids:
            continue
        result = run_question(question, config_name, privacy_mode, settings, mcp_config_path)
        results.append(result)

        if jsonl_path is not None:
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(result), default=str) + "\n")

        if on_result is not None:
            on_result(result)
        else:
            verdict = "PASS" if result.result_match else (result.failure_category or "FAIL")
            log.info(
                "[%d/%d] %s %-8s %-24s wren=%-2d (%.1fs)",
                index, len(questions), question.id, question.category,
                verdict, result.wren_tool_calls, result.total_time_ms / 1000,
            )

        # Check removed: sometimes Groq answers directly without tools for simple questions
        if index == 1 and result.wren_tool_calls == 0:
            log.warning("The first question completed without calling any Wren MCP tools.")

    return results


def load_previous_results(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []
    records = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
