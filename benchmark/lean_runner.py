"""Run the lean suite with conversational state threaded through each thread.

One conversation is one unit of execution. State is created fresh per
conversation and never shared between them, so a standalone question always
starts from genuinely empty context rather than inheriting whatever the
previous question happened to leave behind.

Within a conversation each turn is classified before it is asked. The
classification decides whether the previous state is carried forward, dropped
because the subject changed, or discarded outright, and it is recorded so a
wrong decision is visible on the turn that made it rather than the turn after.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from benchmark.context import (
    ConversationState, classify_turn, render_context, update_state,
)
from benchmark.evaluator import (
    compare_projection_agnostic, compare_results, compare_row_subset,
    result_summary,
)
from benchmark.lean_suite import Conversation, SuiteTurn
from benchmark.sql_semantics import compare as compare_semantics
from benchmark.models import ParsedSQL, Session, Turn
from benchmark.safety import UnsafeSQLError, assert_read_only
from claude.parser import parse_clarification, parse_sql
from config.logging import get_logger
from config.settings import Settings
from database.connection import run_readonly
from llm_api.factory import get_provider

log = get_logger("lean_runner")

GAZETTEER_FILE = Path(__file__).resolve().parents[1] / "metadata" / "entity_gazetteer.yaml"


def load_gazetteer(path: Path | None = None) -> list[str]:
    """Entity values that can end a conversational block.

    Only the 'entity' role is returned. Dimension values such as PVH or Active
    narrow the current subject; treating them as subjects would reset the
    block on "what about PVH?", which is precisely the wrong answer.
    """
    p = path or GAZETTEER_FILE
    if not p.exists():
        log.warning("no gazetteer at %s; topic switching will be disabled", p)
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    values: list[str] = []
    for _, vals in (doc.get("entity") or {}).items():
        values.extend(vals or [])
    return values


@dataclass
class TurnResult:
    turn_id: str
    conversation_id: str
    turn_index: int
    category: str
    question: str

    decision: str = ""
    expected_decision: str | None = None
    decision_match: bool | None = None
    resolved_entity: str | None = None

    expected_sql: str | None = None
    generated_sql: str | None = None
    sql_valid: bool = False
    execution_success: bool = False
    result_match: bool = False
    match_mode: str = ""
    failure_category: str = ""

    # Result matching alone lets a query pass for the wrong reason -- filtering
    # workflow_code instead of business_object_type returns the same rows here
    # and is still wrong. These record the SQL's meaning independently, so the
    # gap between "right rows" and "right query" stays visible.
    semantic_match: bool = False
    semantic_issues: list[str] = field(default_factory=list)
    projection_verdict: str = ""
    semantic_components: dict = field(default_factory=dict)

    expected_behavior: str = "sql"
    clarification: str | None = None
    behavior_match: bool | None = None
    schema_grounded: bool = True
    hallucinated: list[str] = field(default_factory=list)

    expected_result: dict = field(default_factory=dict)
    actual_result: dict = field(default_factory=dict)

    prompt_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    completion_tokens: int = 0
    context_chars: int = 0
    tool_call_count: int = 0
    tools_used: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    llm_ms: float = 0.0
    error: str | None = None
    raw_output: str = ""


def _classify_failure(r: TurnResult, expected, actual) -> str:
    """Name the failure so patterns are visible across the suite."""
    if r.generated_sql is None:
        return "PROMPT_ERROR"
    if not r.sql_valid:
        return "SQL_SYNTAX_ERROR"
    if not r.execution_success:
        err = (r.error or "").lower()
        if "does not exist" in err and "column" in err:
            return "SCHEMA_ERROR"
        if "does not exist" in err and "relation" in err:
            return "SCHEMA_ERROR"
        if "syntax error" in err:
            return "SQL_SYNTAX_ERROR"
        return "TOOL_PIPELINE_ERROR"
    if r.decision_match is False:
        return "CONTEXT_ERROR"

    exp_cols = set(expected.columns or [])
    act_cols = set(actual.columns or [])
    exp_n, act_n = len(expected.rows or []), len(actual.rows or [])

    gen = (r.generated_sql or "").lower()
    ref = (r.expected_sql or "").lower()

    if exp_n != act_n:
        # A row-count miss on a follow-up is nearly always the context, not SQL.
        if r.turn_index > 0:
            return "FOLLOW_UP_ERROR"
        if ("group by" in ref) != ("group by" in gen):
            return "AGGREGATION_ERROR"
        if "join" in ref and "join" in gen:
            return "JOIN_ERROR"
        return "FILTER_ERROR"
    if exp_cols != act_cols:
        return "COLUMN_SELECTION_ERROR"
    return "RESULT_MISMATCH"


# How much of the conversation reaches the model.
#   none    -- nothing; every turn stands alone. The system before this work.
#   history -- the whole thread replayed verbatim. The obvious approach, and
#              the one that grows without bound.
#   state   -- the compact structured state from benchmark.context.
CONTEXT_MODES = ("none", "history", "state")


def run_turn(
    turn: SuiteTurn,
    state: ConversationState,
    gazetteer: list[str],
    settings: Settings,
    mcp_config_path: Path,
    privacy_mode: str,
    session: Session,
    context_mode: str = "state",
) -> TurnResult:
    started = time.perf_counter()
    r = TurnResult(
        turn_id=turn.id, conversation_id=turn.conversation_id,
        turn_index=turn.turn_index, category=turn.category,
        question=turn.question, expected_sql=turn.expected_sql,
        expected_decision=turn.expect_decision,
        expected_behavior=turn.expect_behavior,
    )

    # 1. Decide how this turn relates to the block, before asking anything.
    decision, entity = classify_turn(turn.question, state, gazetteer)
    r.decision, r.resolved_entity = decision, entity
    if turn.expect_decision is not None:
        r.decision_match = decision == turn.expect_decision

    # 2. A new block sees no context at all; a switch drops the old subject's
    #    filters, which is the whole point of detecting one.
    if context_mode == "none":
        context = ""
    elif context_mode == "history":
        context = ""          # provider replays session.turns instead
    else:
        # A rebase keeps its context: the subject changed but the question
        # relies on the shape of the one before it.
        if decision in ("new_block", "switch"):
            context = ""
        else:
            if decision == "rebase":
                state.active_filters = {
                    col: pred for col, pred in state.active_filters.items()
                    if state.active_entity is None or state.active_entity not in pred
                }
                state.active_entity = entity
            context = render_context(state)
    r.context_chars = len(context)

    session.context_block = context or None
    if context_mode != "history":
        # Providers fall back to replaying turns when no block is supplied;
        # in state mode that would double-count, and in none mode it would
        # defeat the point of the baseline.
        session.turns = []

    # 3. Ask.
    provider = get_provider(settings)
    run = provider.ask(turn.question, mcp_config_path, privacy_mode, settings, session)
    r.llm_ms = run.duration_ms
    r.tools_used = list(run.tools_used)
    r.tool_call_count = len(run.tools_used)
    r.prompt_tokens = run.prompt_tokens
    r.completion_tokens = run.completion_tokens
    r.cache_read_tokens = run.cache_read_tokens
    r.cache_write_tokens = run.cache_write_tokens
    r.raw_output = run.result_text
    if run.error:
        r.error = run.error

    parsed = parse_sql(run.result_text)
    r.clarification = parse_clarification(run.result_text)

    # A clarification is not a query, but parse_sql's looser fallbacks will
    # happily lift a fragment out of the prose -- "with SLA status 'Delayed'?"
    # was scraped from a correct clarification and scored as a silent
    # substitution. parse_clarification only fires on a JSON object that has a
    # clarify key and no sql key, so when it fires it is the authority.
    if r.clarification is not None:
        parsed = ParsedSQL(sql=None, strategy="clarification", raw=run.result_text)
    r.generated_sql = parsed.sql

    # Did it do the kind of thing the question called for? A confident query
    # in answer to an unanswerable question is a failure even if it runs, and
    # a clarifying question in answer to a clear one is a failure even though
    # it is cautious.
    if turn.expect_behavior == "clarify":
        r.behavior_match = r.clarification is not None and parsed.sql is None
    elif turn.expect_behavior == "zero_or_clarify":
        # Decided below, once the query has run: clarifying is fine, and so is
        # a query that honestly returns nothing.
        r.behavior_match = None
    else:
        r.behavior_match = parsed.sql is not None

    # Never invent schema. Checked deterministically rather than trusted,
    # because invented SQL fails at execution in a way that looks like any
    # other error.
    if parsed.sql:
        from benchmark.sql_semantics import check_against_schema
        sc = check_against_schema(parsed.sql)
        r.schema_grounded = sc.grounded
        r.hallucinated = sorted(sc.unknown_tables | sc.unknown_columns)

    if parsed.sql:
        try:
            assert_read_only(parsed.sql)
            r.sql_valid = True
        except UnsafeSQLError as exc:
            r.error = r.error or f"unsafe SQL: {exc}"

    if turn.expect_behavior == "zero_or_clarify":
        if r.clarification is not None and parsed.sql is None:
            r.behavior_match = r.result_match = r.semantic_match = True
        elif parsed.sql:
            res = run_readonly(settings, parsed.sql, settings.statement_timeout_ms)
            r.actual_result = result_summary(res)
            r.execution_success = res.ok
            empty = res.ok and (
                not res.rows or (len(res.rows) == 1 and res.rows[0][0] == 0))
            r.behavior_match = r.result_match = r.semantic_match = bool(empty)
            if not empty:
                # Rows came back for a value that does not exist, so a filter
                # was quietly changed to something that does.
                r.failure_category = "SILENT_SUBSTITUTION"
        else:
            r.behavior_match = r.result_match = False
            r.failure_category = "PROMPT_ERROR"
        update_state(state, turn.question, parsed.sql, None, entity, decision)
        session.turns.append(Turn(index=turn.turn_index, question=turn.question,
                                  generated_sql=parsed.sql))
        r.latency_ms = (time.perf_counter() - started) * 1000
        return r

    if turn.expect_behavior == "clarify":
        r.result_match = bool(r.behavior_match)
        r.semantic_match = bool(r.behavior_match)
        if not r.behavior_match:
            r.failure_category = ("HALLUCINATION" if not r.schema_grounded
                                  else "SHOULD_HAVE_CLARIFIED")
        update_state(state, turn.question, None, None, entity, decision)
        session.turns.append(Turn(index=turn.turn_index, question=turn.question,
                                  generated_sql=None))
        r.latency_ms = (time.perf_counter() - started) * 1000
        return r

    expected = run_readonly(settings, turn.expected_sql, settings.statement_timeout_ms)
    r.expected_result = result_summary(expected)

    actual = None
    if r.sql_valid and parsed.sql:
        actual = run_readonly(settings, parsed.sql, settings.statement_timeout_ms)
        r.actual_result = result_summary(actual)
        r.execution_success = actual.ok
        if actual.error:
            r.error = r.error or actual.error
        if actual.ok:
            if compare_results(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "exact"
            elif compare_row_subset(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "superset"
            elif compare_projection_agnostic(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "projection"

    # A turn that answers correctly but misread the conversation is still a
    # defect: the next turn inherits the wrong state.
    if r.result_match and r.decision_match is False:
        r.result_match = False
        r.match_mode = "rows ok, context misread"

    sem = compare_semantics(turn.expected_sql, parsed.sql, ordered=turn.ordered,
                            strict_projection=turn.strict_projection)
    r.semantic_match = sem.semantically_correct
    r.semantic_issues = list(sem.issues)
    r.projection_verdict = sem.projection_verdict
    r.semantic_components = {
        "tables": sem.tables_match, "filters": sem.filters_match,
        "joins": sem.joins_match, "aggregates": sem.aggregates_match,
        "grouping": sem.grouping_match, "ordering": sem.ordering_match,
        "limit": sem.limit_match,
    }

    if not r.result_match:
        r.failure_category = _classify_failure(
            r, expected, actual if actual is not None else expected
        )
    elif not r.schema_grounded:
        r.failure_category = "HALLUCINATION"
    elif not r.semantic_match:
        # Right rows, wrong query. Not counted against result accuracy, but
        # named so it cannot hide behind a passing row comparison.
        r.failure_category = "SEMANTIC_MISMATCH"

    # 4. Fold the turn into the state for whatever comes next. The state
    #    follows the SQL that was actually produced, so a wrong query is
    #    visible in the next turn's context rather than silently corrected.
    update_state(
        state if decision == "follow_up" else state,
        turn.question,
        parsed.sql or turn.expected_sql,
        len(actual.rows) if actual is not None and actual.ok else None,
        entity,
        decision,
    )
    session.turns.append(Turn(index=turn.turn_index, question=turn.question,
                              generated_sql=parsed.sql))

    r.latency_ms = (time.perf_counter() - started) * 1000
    return r


def run_suite(
    conversations: list[Conversation],
    settings: Settings,
    mcp_config_path: Path,
    privacy_mode: str,
    jsonl_path: Path | None = None,
    on_result: Callable[[TurnResult], None] | None = None,
    context_mode: str = "state",
) -> list[TurnResult]:
    if context_mode not in CONTEXT_MODES:
        raise ValueError(f"context_mode must be one of {CONTEXT_MODES}")
    gazetteer = load_gazetteer()
    log.info("gazetteer: %d entity value(s)", len(gazetteer))

    results: list[TurnResult] = []
    for conv in conversations:
        state = ConversationState()
        session = Session(session_id=conv.id, turns=[])
        for turn in conv.turns:
            r = run_turn(turn, state, gazetteer, settings,
                         mcp_config_path, privacy_mode, session,
                         context_mode=context_mode)
            results.append(r)

            if jsonl_path is not None:
                jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with jsonl_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(asdict(r), default=str) + "\n")

            if on_result is not None:
                on_result(r)
            else:
                verdict = ("PASS" if r.result_match and r.semantic_match
                           else "PASS*" if r.result_match
                           else (r.failure_category or "FAIL"))
                dec = r.decision if r.decision_match is not False else f"{r.decision}!"
                log.info("  %-7s %-10s %-22s ctx=%-4d tok=%-6d %.1fs",
                         r.turn_id, dec, verdict, r.context_chars,
                         r.prompt_tokens, r.latency_ms / 1000)
    return results
