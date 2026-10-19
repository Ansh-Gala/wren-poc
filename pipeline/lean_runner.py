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
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from pipeline.context import (
    ConversationState, _EXPLICIT_RESET, accept_recap, classify_turn,
    detect_entity, remember_question,
    is_complete_request, render_context, update_state, without_entity_filters,
)
from pipeline.identity import CallerIdentity, render_identity
from pipeline.followup import (
    FollowUp, clarify_entity, decide, resolve_clarification,
)
from pipeline.normalize import normalize
from pipeline.evaluator import (
    LOGGED_ROWS, compare_projection_agnostic, compare_results, compare_row_subset,
    first_rows, result_summary,
)
from pipeline.lean_suite import Conversation, SuiteTurn
from pipeline.chart_check import MAX_ROWS as CHART_MAX_ROWS, TIMEOUT_MS as CHART_TIMEOUT_MS
from pipeline.sql_semantics import check_against_schema, compare as compare_semantics
from pipeline.models import ParsedSQL, QueryResult, Session, Turn
from pipeline.safety import UnparseableSQLError, UnsafeSQLError, assert_read_only
from claude.prompts import build_repair_question
from claude.parser import (
    partial_sql,
    sql_value_end,
    parse_clarification, parse_clarify_about, parse_explanation, parse_goal,
    chart_sql, parse_chart, parse_group, parse_next, parse_recap,
    parse_options, parse_sql,
)
from config.logging import get_logger
from config.settings import Settings
from database.connection import run_readonly
from llm_api.factory import get_provider, llm_identity

log = get_logger("lean_runner")

# Stands in for a comparison target that does not exist, so the failure
# classifier can be reused on turns that have no expected answer.
_NO_RESULT = QueryResult(columns=[], rows=[], duration_ms=0.0)

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


# Ways of saying "not like that". Matched against the question as typed, so
# the check is over before the model is asked anything.
_NO_GROUPING = re.compile(
    r"\b(no|without|don'?t|do not|never|stop|avoid)\s+group(ing|ed|s)?\b"
    r"|\bungroup(ed)?\b"
    r"|\bnot\s+grouped\b",
    re.IGNORECASE,
)


def says_no_grouping(question: str | None) -> bool:
    """Whether the reader asked for this answer NOT to be collected."""
    return bool(question) and bool(_NO_GROUPING.search(question))


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
    # None when there was no expected answer to compare against, which is the
    # case for every question a person asks through the console.
    result_match: bool | None = False
    match_mode: str = ""
    failure_category: str = ""

    # Result matching alone lets a query pass for the wrong reason -- filtering
    # workflow_code instead of initiative_type returns the same rows here
    # and is still wrong. These record the SQL's meaning independently, so the
    # gap between "right rows" and "right query" stays visible.
    semantic_match: bool | None = False
    semantic_issues: list[str] = field(default_factory=list)
    projection_verdict: str = ""
    semantic_components: dict = field(default_factory=dict)

    expected_behavior: str = "sql"
    clarification: str | None = None
    # The readings the model offered with a clarification, its plain account of
    # what it understood, its restatement of the aim, and the follow-up
    # questions it thinks are worth asking. All optional on the wire: a reply
    # carrying none of them leaves these empty and the turn runs as before.
    clarification_options: list[str] = field(default_factory=list)
    # The column the clarification is about, when the model named one. Used to
    # look up the values worth offering; never shown.
    clarify_about: str | None = None
    # The model's rewritten summary of the thread, before the ingest guard.
    recap: str | None = None
    explanation: str | None = None
    restated_goal: str | None = None
    next_questions: list[str] = field(default_factory=list)
    # Whether the model asked for these rows to be collected under headings.
    # False unless it said so: a plain list is the normal answer.
    grouped: bool = False
    behavior_match: bool | None = None
    schema_grounded: bool = True
    hallucinated: list[str] = field(default_factory=list)

    expected_result: dict = field(default_factory=dict)
    actual_result: dict = field(default_factory=dict)
    # Requirements from expect_columns the answer did not satisfy.
    missing_columns: list[str] = field(default_factory=list)

    # ------------------------------------------------- follow-up layer --
    # Recorded separately from result_match on purpose. A turn can write a
    # perfect query and offer a useless continuation, or repair a typo and
    # then get the SQL wrong; folding them into one number would hide both,
    # and the before/after comparison of SQL accuracy has to stay clean.
    normalized_question: str = ""
    repairs: list[dict] = field(default_factory=list)
    expect_normalized: str | None = None
    normalized_match: bool | None = None

    followup_type: str = "none"
    followup: dict = field(default_factory=dict)
    expected_followup: str | None = None
    followup_match: bool | None = None
    expected_action: dict | None = None
    action_match: bool | None = None
    # True when the clarification was decided without asking the model at all.
    preflight_clarified: bool = False
    # What the user typed, when this turn was an answer to a question the
    # system asked and was resolved back into the original wording.
    resumed_from: str | None = None
    resumed_answering: str | None = None

    prompt_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    completion_tokens: int = 0
    context_chars: int = 0
    tool_call_count: int = 0
    tools_used: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    # What the CLI says the query cost. Excludes its own startup.
    llm_ms: float = 0.0
    # What the caller actually waited for the model leg, startup included.
    # llm_wall_ms - llm_ms is process overhead, and it was the largest single
    # cost in a turn before the pool existed.
    llm_wall_ms: float = 0.0
    # Per-stage wall clock, so a regression can be attributed rather than
    # guessed at. Every one is measured; none is derived.
    normalize_ms: float = 0.0
    schema_check_ms: float = 0.0
    safety_ms: float = 0.0
    db_ms: float = 0.0
    # What a second attempt cost, and whether it was worth it. Zero and False
    # on the overwhelming majority of turns, which never reach a repair.
    repair_ms: float = 0.0
    repair_attempted: bool = False
    repair_succeeded: bool = False
    repaired_from: str | None = None
    followup_ms: float = 0.0
    error: str | None = None
    # Carried from QueryResult so the HTTP layer can turn a failure into
    # something a person can act on without reading the raw message, which
    # names the table and column it failed on.
    sqlstate: str | None = None
    raw_output: str = ""

    # Kept for the chat history row, as Drupal keeps them. Who answered: the
    # CLI is mode "cli", provider "claude-cli"; an API is mode "api" and its
    # vendor. The model is the one configured.
    llm_mode: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    timed_out: bool = False
    parse_strategy: str = "none"
    # The user said to start over: where the history stops reading questions.
    context_reset: bool = False
    # Wall-clock start of the turn, as a unix time, for the history row.
    turn_started: float = 0.0

    # The chart the model asked for, its own query's result and why that
    # query failed, and the verdict the HTTP layer reached on the chart. All
    # empty when no chart was asked for.
    chart: dict | None = None
    chart_result: dict | None = None
    chart_error: str | None = None
    chart_reason: str | None = None


def _classify_failure(r: TurnResult, expected, actual) -> str:
    """Name the failure so patterns are visible across the suite."""
    if r.generated_sql is None:
        return "PROMPT_ERROR"
    if not r.sql_valid:
        return "SQL_SYNTAX_ERROR"
    # Refused before it ran, for naming what the schema does not have.
    if not r.schema_grounded:
        return "HALLUCINATION"
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
#   state   -- the compact structured state from pipeline.context.
CONTEXT_MODES = ("none", "history", "state")


def _has_expectations(turn: SuiteTurn) -> bool:
    """Whether this turn came from a suite rather than from a person.

    A benchmark turn always states something: the SQL it should produce, or --
    when there is no valid SQL answer -- the behaviour it should choose
    instead. A question typed into the console states neither, and scoring it
    against the defaults would report defects nobody observed.

    expect_columns counts as a statement of its own: a turn may name the
    columns its answer must carry without naming the SQL, because more than
    one query is often right and only the projection is really being asked
    about.
    """
    return (turn.expected_sql is not None
            or turn.expect_behavior != "sql"
            or bool(turn.expect_columns))


def _action_matches(followup: FollowUp, expected: dict | None) -> bool | None:
    """Whether some suggestion carries the action the case asked for.

    Compared as a subset of one suggestion's action, not as an exact match on
    the whole list. A case cares that "group by status" is on offer; it does
    not care what else is, nor in what order, nor whether the contract later
    grows a field.
    """
    if expected is None:
        return None
    for suggestion in followup.suggestions:
        actual = suggestion.action.to_dict()
        if all(actual.get(k) == v for k, v in expected.items()):
            return True
    return False


def _unanswered_question(pending: FollowUp) -> str:
    """A question the user has not answered yet, with what was offered.

    Written flat rather than as a list, because render_context flattens
    whitespace before it prints this -- so the numbering has to survive as
    text, not as layout.
    """
    question = " ".join((pending.question or "").split())
    numbered = [
        f"({i + 1}) {' '.join(s.label.split())}"
        for i, s in enumerate(pending.suggestions)
        if (s.label or "").strip()
    ]
    if not numbered:
        return question
    return f"{question} -- the choices you offered, in this order: " + "; ".join(numbered) + "."


def _attach_followup(
    r: TurnResult,
    turn: SuiteTurn,
    state: ConversationState,
    row_count: int | None,
    followup_mode: bool,
) -> None:
    """Decide what to offer next, and score it against the case."""
    if not followup_mode:
        return
    # The executed result, so a breakdown is only offered where the rows can
    # support one. r already carries it -- set before this is reached on every
    # path -- so this needs no new argument.
    followup = decide(state, row_count, r.clarification, r.actual_result,
                      r.clarification_options, r.next_questions, r.clarify_about)
    r.followup_type = followup.type
    r.followup = followup.to_dict()
    # Set after update_state, which resets the block and would clear it.
    if followup.type == "clarification":
        # Candidates let the next turn resolve by matching the reply against
        # what was offered. Without them there is nothing to match, so the
        # question itself is carried instead -- otherwise the system asks
        # things it structurally cannot hear the answer to.
        if followup.suggestions:
            state.pending_clarification = followup
            state.pending_question = r.normalized_question or r.question
        else:
            state.awaiting_answer_to = followup.question
    if turn.expect_followup is not None:
        r.followup_match = followup.type == turn.expect_followup
    r.action_match = _action_matches(followup, turn.expect_action)


# ---------------------------------------------------------- early execution --
#
# The reply is one JSON object and the contract puts `sql` first in it.
# Measured with `claude --include-partial-messages` across three questions,
# the SQL is complete a mean of 2.02 seconds before the last token -- the rest
# of that time writes explanation, goal, recap and next. Running the query in
# that gap rather than after it is worth about two seconds to whoever is
# waiting for a table.
#
# The execution is published into a memo that run_turn's own call sites read,
# rather than run_turn being restructured around it. run_turn is long, and
# every accuracy figure in results/ was produced by it; the alternative to a
# memo was either rewriting that or running the user's query twice.


def _execute(settings: Settings, sql: str, timeout_ms: int,
             memo: dict | None = None) -> QueryResult:
    """Run `sql`, or hand back the run that already happened.

    The memo is per turn and keyed on the statement, so it can only ever
    return the result of the identical query. It is consulted, never
    populated, on this path: only the early execution puts anything in it, and
    only after the same two gates run_turn applies.
    """
    if memo is not None and sql in memo:
        return memo[sql]
    return run_readonly(settings, sql, timeout_ms)


def _run_chart_query(r: "TurnResult", settings: Settings, memo: dict) -> None:
    """Run the chart's own query, through the main query's gates.

    Ported from the Drupal port's TurnRunner::runChartQuery. Called only once
    the main query has returned rows. Never after a repair: the turn's time
    budget is spent by then. No repair either, since a chart is not worth a
    second model call. Any failure sets chart_error and drops the chart; the
    main answer is never touched, and the chart never falls back to the main
    rows.
    """
    chart = r.chart
    if not isinstance(chart, dict) or "invalid" in chart or "sql" not in chart:
        return
    if r.repair_attempted:
        r.chart_error = "skipped"
        return
    sql = chart_sql(chart["sql"])
    if sql is None:
        r.chart_error = "malformed"
        return
    try:
        assert_read_only(sql)
    except UnsafeSQLError:
        r.chart_error = "refused"
        return
    if not check_against_schema(sql).grounded:
        r.chart_error = "ungrounded"
        return
    result = _execute(settings, sql, CHART_TIMEOUT_MS, memo)
    if not result.ok:
        # query_canceled: the statement timeout fired.
        r.chart_error = "timeout" if result.sqlstate == "57014" else "db_error"
        return
    # More rows than the cap mark the result truncated, which chart_check
    # refuses, and keep the rest out of the turn result.
    r.chart_result = {**result_summary(result, max_rows=CHART_MAX_ROWS),
                      "duration_ms": result.duration_ms}


def _execute_early(settings: Settings, text: str, memo: dict,
                   on_sql: Callable[[dict], None]) -> None:
    """Vet and run the SQL out of a reply that is still arriving.

    Declining is always safe: nothing is memoised, and run_turn then runs the
    query itself exactly as it does today. So this applies the two gates
    rather than reproducing the decisions that follow from them.

    Both gates are required, and grounding is the one that matters. run_turn
    refuses to execute ungrounded SQL because the rows *are* the schema --
    "show me the columns of that table" answered out of information_schema is
    a disclosure no wording guard can reach. Executing here without that check
    would reopen it behind run_turn's back.
    """
    sql = partial_sql(text)
    if not sql or _gated(sql) is None:
        return

    res = _execute(settings, sql, settings.statement_timeout_ms)
    memo[sql] = res
    on_sql({
        "generated_sql": sql,
        "sql_valid": True,
        "schema_grounded": True,
        "execution_success": res.ok,
        "error": res.error,
        "sqlstate": res.sqlstate,
        "actual_result": result_summary(res, max_rows=None),
    })


def _delta_watcher(settings: Settings, memo: dict,
                   on_sql: Callable[[dict], None]) -> Callable[[str], None]:
    """An on_delta that fires once, the moment the sql value closes.

    A clarification carries no sql key, so the mark never arrives and this
    never fires -- which is correct, and is why the caller must not wait for
    it.
    """
    buf: list[str] = []
    fired = False

    def on_delta(piece: str) -> None:
        nonlocal fired
        buf.append(piece)
        if fired:
            return
        text = "".join(buf)
        if sql_value_end(text) is None:
            return
        fired = True
        try:
            _execute_early(settings, text, memo, on_sql)
        except Exception:
            # An answer matters more than the two seconds. Whatever went
            # wrong here, run_turn is about to do the same work itself.
            log.exception("early execution failed; falling back")

    return on_delta


def _reads_as_zero(value) -> bool:
    """Drupal's ``(string) $rows[0][0] === '0'``, on PostgreSQL's text for it.

    A count of 0 and the text '0' are nothing; 0.00 from a numeric is a value.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        # float8 zero prints as "0", negative zero as "-0".
        return value == 0 and math.copysign(1.0, value) > 0
    return str(value) == "0"


def _gated(sql: str):
    """The schema check, when `sql` passes both gates; else None."""
    sc = check_against_schema(sql)
    if not sc.grounded:
        return None
    try:
        assert_read_only(sql)
    except UnsafeSQLError:
        return None
    return sc


def _add_tokens(r: TurnResult, run) -> None:
    r.prompt_tokens += run.prompt_tokens
    r.completion_tokens += run.completion_tokens
    r.cache_read_tokens += run.cache_read_tokens
    r.cache_write_tokens += run.cache_write_tokens


def _second_attempt(question, sql, error, settings, mcp_config_path, privacy_mode,
                    r: TurnResult, executed):
    """The one repair: ask again with the error, gate the answer, run it.

    Returns (fixed SQL, its schema check, its result) when the corrected
    statement passed both gates and ran; None leaves the first failure
    standing, because that is the one the user's question produced.
    """
    # Set before the call, not after: this counts how often a turn needed a
    # second attempt, which is the figure worth having. Whether the attempt
    # produced anything usable is repair_succeeded.
    r.repair_attempted = True
    try:
        fixed, cost_ms = _repair(question, sql, error, settings, mcp_config_path,
                                 privacy_mode, r)
    except Exception:
        # The original failure is still reported; a repair that cannot run
        # must not turn a failed query into a crash.
        fixed, cost_ms = None, 0.0
    r.repair_ms = cost_ms
    if not fixed:
        return None
    # The corrected statement goes through the same two gates as the first
    # one. A repair must not become the way round them.
    sc = _gated(fixed)
    if sc is None:
        return None
    retried = _execute(settings, fixed, settings.statement_timeout_ms, executed)
    r.db_ms += retried.duration_ms
    return (fixed, sc, retried) if retried.ok else None


def _take_repair(r: TurnResult, parsed: ParsedSQL, fixed: str, sc) -> ParsedSQL:
    """The turn now carries the corrected statement; the first is kept."""
    r.repair_succeeded = True
    r.repaired_from = parsed.sql
    r.parse_strategy = "repair"
    r.generated_sql = fixed
    r.schema_grounded = sc.grounded
    r.hallucinated = sorted(sc.unknown_tables | sc.unknown_columns)
    return ParsedSQL(sql=fixed, strategy="repair", raw=parsed.raw)


def _repair(
    question: str,
    sql: str,
    error: str,
    settings: Settings,
    mcp_config_path,
    privacy_mode: str,
    r: TurnResult,
) -> tuple[str | None, float]:
    """One more attempt, with the database's complaint attached.

    Postgres says precisely what is wrong -- "DISTINCT is not implemented for
    window functions", "column x does not exist". Until this existed that
    sentence was read, sanitised for the user and thrown away, so the model
    that wrote the query never learned it had written something impossible.

    Exactly one attempt, and only for a statement the database rejected. A
    loop here would turn a bad question into an unbounded bill, and a second
    failure is a signal worth showing rather than grinding at.

    No session and no context: the repair is about this statement and this
    error, and replaying the conversation would invite the model to revisit
    what the question meant instead of fixing what was named.

    Returns the corrected SQL and what the call cost in milliseconds. None
    means the attempt produced nothing usable, and the caller keeps the
    original failure -- a repair that cannot help must not make things worse.

    The call's tokens are added to ``r``, as Drupal adds them, so the turn
    records what it really cost.
    """
    provider = get_provider(settings)
    run = provider.ask(
        build_repair_question(question, sql, error),
        mcp_config_path, privacy_mode, settings, None,
    )
    # Counted before any return: a repair that fails still cost tokens.
    _add_tokens(r, run)
    if not run.ok or not run.result_text:
        return None, run.duration_ms
    fixed = parse_sql(run.result_text).sql
    # A repair that hands back the same statement has not repaired anything,
    # and running it again would fail the same way for the same reason.
    if not fixed or fixed.strip() == sql.strip():
        return None, run.duration_ms
    return fixed, run.duration_ms


def run_turn(
    turn: SuiteTurn,
    state: ConversationState,
    gazetteer: list[str],
    settings: Settings,
    mcp_config_path: Path,
    privacy_mode: str,
    session: Session,
    context_mode: str = "state",
    followup_mode: bool = True,
    identity: CallerIdentity | None = None,
    on_sql: Callable[[dict], None] | None = None,
    repair_mode: bool = True,
) -> TurnResult:
    """One turn, end to end.

    ``on_sql`` is optional and changes nothing about the answer. When it is
    set the reply is streamed, and the moment the sql value closes the query
    is vetted, run and handed over -- about two seconds before the last token
    on the measurements in the stream-SQL-early design (2026-09-23, now in git history).
    The turn then finishes exactly as it would have, reusing that execution
    rather than repeating it. A reply that clarifies has no sql and never
    calls it.
    """
    started = time.perf_counter()
    # Filled only by the early execution, read only by the two call sites
    # below that run the generated SQL.
    executed: dict = {}
    r = TurnResult(
        turn_id=turn.id, conversation_id=turn.conversation_id,
        turn_index=turn.turn_index, category=turn.category,
        question=turn.question, expected_sql=turn.expected_sql,
        expected_decision=turn.expect_decision,
        expected_behavior=turn.expect_behavior,
        expect_normalized=turn.expect_normalized,
        expected_followup=turn.expect_followup,
        expected_action=turn.expect_action,
    )
    r.turn_started = time.time()

    # 0. Repair the question before anything reads it. A misspelt schema term
    #    is not a hard question, but it reaches the model as a word the schema
    #    has never heard of, and the model can then only guess or ask. This
    #    costs no tokens and no round-trip.
    question = turn.question
    if followup_mode:
        _t = time.perf_counter()
        repaired = normalize(turn.question)
        r.normalize_ms = (time.perf_counter() - _t) * 1000
        question = repaired.question
        r.repairs = [asdict(x) for x in repaired.repairs]
    r.normalized_question = question
    if turn.expect_normalized is not None:
        r.normalized_match = question == turn.expect_normalized

    # 0b. If the previous turn asked something, this one may be the answer.
    #     Resolved into the original question rather than sent on as a bare
    #     noun: "AR_YD_Suiting" alone reaches the model with empty context and
    #     it can only ask what to do with it, so the thread deadlocks one turn
    #     after the clarification meant to unblock it.
    resumed = None
    unresolved = None
    if followup_mode and state.pending_clarification is not None:
        pending, asked_about = state.pending_clarification, state.pending_question
        state.pending_clarification, state.pending_question = None, ""
        resumed = resolve_clarification(question, asked_about, pending)
        if resumed is not None:
            r.resumed_from = question
            # Which question the reply answered. Kept because the reply on its
            # own is unreadable after the fact -- a stored turn saying only
            # that the user typed "4" records nothing about what they chose.
            r.resumed_answering = pending.question
            question = resumed
            r.normalized_question = question
        else:
            # Held for step 1. Failing to match is not the same as the reply
            # having nothing to do with the question: "the one about backlog"
            # is an answer this cannot read, and sending it on alone is what
            # makes the model say it has no idea what the user is talking
            # about.
            unresolved = pending

    # 1. Decide how this turn relates to the block, before asking anything.
    decision, entity = classify_turn(question, state, gazetteer)
    if resumed is not None:
        # The resumed text is the original question, so it starts a block in
        # its own right; naming it separately keeps the resumption visible.
        decision = "clarification_response"
        entity = detect_entity(question, gazetteer)
    # A reply to a question the system asked is an answer, not a new topic --
    # unless the user ignored the question and asked something whole instead,
    # which they are entitled to do.
    if (followup_mode and resumed is None and state.awaiting_answer_to
            and not is_complete_request(question)):
        decision = "clarification_response"
    # A reply this could not read still belongs to the question that prompted
    # it. Carrying the question and its options into the context lets the model
    # resolve what the matcher could not -- "the second one", "that one", a
    # number against readings it wrote itself -- rather than receiving a bare
    # token and truthfully reporting that it has no idea what the conversation
    # is about.
    #
    # Held on awaiting_answer_to rather than by keeping pending_clarification
    # alive, and that is the whole of why this cannot wedge: update_state has
    # no branch for clarification_response, so a pending kept here would be
    # cleared only by a reset, whereas awaiting_answer_to is nulled further
    # down on every turn.
    if (followup_mode and resumed is None and unresolved is not None
            and not is_complete_request(question)
            and not _EXPLICIT_RESET.match(question)):
        state.awaiting_answer_to = _unanswered_question(unresolved)
        decision = "clarification_response"

    # An inferred switch keeps the recap; only the user saying so drops it.
    # The distinction is the point: the classifier noticing a change of
    # subject is not the same as being told the thread is over.
    if _EXPLICIT_RESET.match(question):
        state.forget_history()
        r.context_reset = True

    r.decision, r.resolved_entity = decision, entity
    if turn.expect_decision is not None:
        r.decision_match = decision == turn.expect_decision

    # 2. The context block. A rebase keeps the shape of the question before it
    #    but drops the old subject's filters; every other decision renders the
    #    state as update_state left it.
    if context_mode in ("none", "history"):
        context = ""          # history: the provider replays session.turns
    else:
        if decision == "rebase":
            state.active_filters = without_entity_filters(state)
            state.active_entity = entity
        context = render_context(state)
    # Who is asking rides at the top of the same block, on every turn --
    # including the first, which has no conversation context at all. It is not
    # conversation state: it does not accumulate, a switch does not drop it,
    # and nothing the model says can change it.
    # After the block is built, so a question is never in its own history.
    remember_question(state, question)
    context = render_identity(identity) + context
    r.context_chars = len(context)
    state.awaiting_answer_to = None
    # Named for this turn only; the SQL that runs now carries the change.
    state.dropped_filters = []

    # In history mode a block would replace the replayed turns, so none is
    # set; the identity is lost there, and "my tasks" asks who is asking.
    session.context_block = None if context_mode == "history" else (context or None)
    if context_mode != "history":
        # Providers fall back to replaying turns when no block is supplied;
        # in state mode that would double-count, and in none mode it would
        # defeat the point of the baseline.
        session.turns = []

    # 2b. Some questions can be settled without asking at all. "Show the AR_YD
    #     items" names no type that exists, but three of them start with
    #     AR_YD, and the gazetteer knows which three. Asking the model to pick
    #     invites it to pick one; asking the user costs nothing and is right.
    if followup_mode:
        preflight = clarify_entity(question, gazetteer)
        if preflight is not None:
            r.preflight_clarified = True
            r.followup_type, r.followup = preflight.type, preflight.to_dict()
            r.clarification = preflight.question
            if turn.expect_followup is not None:
                r.followup_match = preflight.type == turn.expect_followup
            r.action_match = _action_matches(preflight, turn.expect_action)
            if not _has_expectations(turn):
                # A real question, asked by a person. Clarifying is the system
                # working; scoring it against expect_behavior's "sql" default
                # would paint its best behaviour as a failure.
                r.result_match = r.semantic_match = None
            elif turn.expect_behavior in ("clarify", "zero_or_clarify"):
                r.behavior_match = r.result_match = r.semantic_match = True
            else:
                r.behavior_match = False
                r.failure_category = "SHOULD_NOT_HAVE_CLARIFIED"
            update_state(state, question, None, None, entity, decision)
            session.turns.append(Turn(index=turn.turn_index, question=question,
                                      generated_sql=None))
            # After update_state, which resets the block and would clear it.
            state.pending_clarification = preflight
            state.pending_question = question
            r.latency_ms = (time.perf_counter() - started) * 1000
            return r

    # 3. Ask.
    provider = get_provider(settings)
    # Passed only when a caller asked to be told early. Sending on_delta=None
    # would still be sending it, and a provider written before streaming
    # existed -- or a test double standing in for one -- takes five arguments
    # and rejects a sixth.
    streaming = {"on_delta": _delta_watcher(settings, executed, on_sql)} if on_sql else {}
    run = provider.ask(question, mcp_config_path, privacy_mode, settings, session,
                       **streaming)
    r.llm_mode, r.llm_provider, r.llm_model = llm_identity(settings)
    r.timed_out = run.timed_out
    r.llm_ms = run.duration_ms
    r.llm_wall_ms = run.wall_ms or run.duration_ms
    r.tools_used = list(run.tools_used)
    r.tool_call_count = len(run.tools_used)
    _add_tokens(r, run)
    r.raw_output = run.result_text
    if run.error:
        r.error = run.error

    parsed = parse_sql(run.result_text)
    r.clarification = parse_clarification(run.result_text)
    r.explanation = parse_explanation(run.result_text)
    r.clarification_options = parse_options(run.result_text)
    r.clarify_about = parse_clarify_about(run.result_text)
    r.recap = parse_recap(run.result_text)
    r.next_questions = parse_next(run.result_text)
    r.restated_goal = parse_goal(run.result_text)
    # The model is told never to group when asked not to, and mostly does not.
    # "Must not be grouped" is not a thing to leave to mostly, so the words are
    # checked here as well: a reader who says it should not have to say it
    # twice.
    r.grouped = parse_group(run.result_text) and not says_no_grouping(question)
    r.chart = parse_chart(run.result_text)

    # A clarification is not a query, but parse_sql's looser fallbacks will
    # happily lift a fragment out of the prose -- "with SLA status 'Delayed'?"
    # was scraped from a correct clarification and scored as a silent
    # substitution. parse_clarification only fires on a JSON object that has a
    # clarify key and no sql key, so when it fires it is the authority.
    if r.clarification is not None:
        parsed = ParsedSQL(sql=None, strategy="clarification", raw=run.result_text)
    r.generated_sql = parsed.sql
    r.parse_strategy = parsed.strategy

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
        _t = time.perf_counter()
        sc = check_against_schema(parsed.sql)
        r.schema_check_ms = (time.perf_counter() - _t) * 1000
        r.schema_grounded = sc.grounded
        r.hallucinated = sorted(sc.unknown_tables | sc.unknown_columns)

    unreadable = None
    if parsed.sql:
        _t = time.perf_counter()
        try:
            assert_read_only(parsed.sql)
            r.sql_valid = True
        except UnsafeSQLError as exc:
            if isinstance(exc, UnparseableSQLError):
                unreadable = str(exc)
            r.error = r.error or f"unsafe SQL: {exc}"
            # "Please try rephrasing" is the wrong advice for someone asking
            # what the tables are -- rephrasing cannot help, because the
            # question is not about the work. 42703's safe text says the
            # useful thing instead: ask about tasks, initiatives, users,
            # departments or roles.
            if "system catalogue" in str(exc) or "system function" in str(exc):
                r.sqlstate = r.sqlstate or "42703"
        r.safety_ms = (time.perf_counter() - _t) * 1000

    if turn.expect_behavior == "zero_or_clarify":
        if r.clarification is not None and parsed.sql is None:
            r.behavior_match = r.result_match = r.semantic_match = True
        elif parsed.sql and not (r.sql_valid and r.schema_grounded):
            # Refused by a gate, so never run: the gates hold on this path too.
            r.behavior_match = r.result_match = r.semantic_match = False
            r.failure_category = ("HALLUCINATION" if not r.schema_grounded
                                  else "SQL_SYNTAX_ERROR")
        elif parsed.sql:
            res = _execute(settings, parsed.sql, settings.statement_timeout_ms, executed)
            r.db_ms += res.duration_ms
            r.actual_result = result_summary(res, max_rows=None)
            r.execution_success = res.ok
            empty = res.ok and (not res.rows or (
                len(res.rows) == 1 and res.rows[0] and _reads_as_zero(res.rows[0][0])))
            r.behavior_match = r.result_match = r.semantic_match = bool(empty)
            if not empty:
                # Rows came back for a value that does not exist, so a filter
                # was quietly changed to something that does.
                r.failure_category = "SILENT_SUBSTITUTION"
        else:
            r.behavior_match = r.result_match = False
            r.failure_category = "PROMPT_ERROR"
        update_state(state, question, parsed.sql, None, entity, decision)
        session.turns.append(Turn(index=turn.turn_index, question=question,
                                  generated_sql=parsed.sql))
        _attach_followup(r, turn, state, None, followup_mode)
        r.latency_ms = (time.perf_counter() - started) * 1000
        return r

    if turn.expect_behavior == "clarify":
        r.result_match = bool(r.behavior_match)
        r.semantic_match = bool(r.behavior_match)
        if not r.behavior_match:
            r.failure_category = ("HALLUCINATION" if not r.schema_grounded
                                  else "SHOULD_HAVE_CLARIFIED")
        update_state(state, question, None, None, entity, decision)
        session.turns.append(Turn(index=turn.turn_index, question=question,
                                  generated_sql=None))
        _attach_followup(r, turn, state, None, followup_mode)
        r.latency_ms = (time.perf_counter() - started) * 1000
        return r

    # A turn asked by a person has no known-correct answer to compare against,
    # which is how the QA console reaches this code. Everything above is
    # identical either way; only the scoring is skipped, and the verdicts are
    # left as None rather than False -- "not applicable" and "wrong" must not
    # look alike, or every real question would read as a failure and be given a
    # failure_category naming a defect nobody observed.
    # A turn may state only the columns its answer must carry, with no SQL to
    # compare rows against. Row comparison is skipped for those; the column
    # floor is still checked.
    scoring = turn.expected_sql is not None or bool(turn.expect_columns)
    comparing_rows = turn.expected_sql is not None

    expected = None
    if comparing_rows:
        expected = run_readonly(settings, turn.expected_sql, settings.statement_timeout_ms)
        r.db_ms += expected.duration_ms
        r.expected_result = result_summary(expected)

    actual = None
    # SQL the parser cannot read. Drupal's gate matches patterns, so there the
    # database rejects such a statement as a syntax error and the one repair
    # runs. Here the parser refused it first and nothing was repaired -- even
    # valid PostgreSQL that sqlglot cannot read. It is still never run: the
    # repair goes on the parser's words, and its answer must pass both gates.
    if unreadable and repair_mode:
        repaired = _second_attempt(question, parsed.sql, unreadable, settings,
                                   mcp_config_path, privacy_mode, r, executed)
        if repaired:
            fixed, sc, actual = repaired
            r.sql_valid = True
            r.error = r.sqlstate = None
            parsed = _take_repair(r, parsed, fixed, sc)

    # Grounding is a gate, not a note.
    #
    # The check above already knew the query named something the described
    # schema does not have, and its answer was used only to label the failure
    # afterwards. So "show me the columns of that table" was answered out of
    # information_schema, and the answer WAS the schema -- returned as rows,
    # where no guard on the wording can reach it. The rows are the leak, so
    # the only thing that stops it is not running the query.
    #
    # It also closes every other table in the database at once: the role holds
    # SELECT on far more than the TMS views, and the schema file is now the
    # boundary of what is answerable.
    if r.sql_valid and parsed.sql and not r.schema_grounded:
        r.error = r.error or (
            "refused: the query names objects outside the described schema: "
            + ", ".join(r.hallucinated or []))
        # undefined_column. Its safe message already says the right thing:
        # ask about tasks, initiatives, users, departments or roles.
        r.sqlstate = r.sqlstate or "42703"
        r.execution_success = False
    elif r.sql_valid and parsed.sql:
        # Already run when it was the repair of an unreadable statement.
        if actual is None:
            actual = _execute(settings, parsed.sql, settings.statement_timeout_ms, executed)
            r.db_ms += actual.duration_ms

            # The database rejected the statement, and it said why. Tell the
            # model and let it try once more. Only here: a refusal above is a
            # decision this pipeline made on purpose, and asking the model to
            # work around one would be asking it to defeat a gate.
            if not actual.ok and actual.error and repair_mode:
                repaired = _second_attempt(question, parsed.sql, actual.error, settings,
                                           mcp_config_path, privacy_mode, r, executed)
                if repaired:
                    fixed, sc, actual = repaired
                    parsed = _take_repair(r, parsed, fixed, sc)

        # Every row, as Drupal keeps them: the follow-up layer reads the whole
        # answer. What is shown, or written to a log, is cut later.
        r.actual_result = result_summary(actual, max_rows=None)
        r.execution_success = actual.ok
        if actual.ok and actual.rows:
            _run_chart_query(r, settings, executed)
        if actual.error:
            r.error = r.error or actual.error
            r.sqlstate = r.sqlstate or actual.sqlstate
        if actual.ok and comparing_rows:
            if compare_results(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "exact"
            elif compare_row_subset(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "superset"
            elif compare_projection_agnostic(expected, actual, turn.ordered):
                r.result_match, r.match_mode = True, "projection"

    if scoring and turn.expect_columns:
        # The answer has to carry what the question asked about, whatever the
        # rows say. A list of task ids is the right rows for "tasks which have
        # issues" and none of the answer.
        #
        # A requirement is satisfied by a column that contains it, not only by
        # one that equals it: the model names its aggregates itself, so
        # "count" has to be met by file_count and issue_count alike. Listing
        # every alias a model might invent is a losing game.
        returned = [str(c).lower() for c in (r.actual_result.get("columns") or [])]
        def _met(name: str) -> bool:
            wanted = name.lower()
            return any(wanted == col or wanted in col for col in returned)
        missing = [group for group in turn.expect_columns
                   if not any(_met(name) for name in group)]
        if missing:
            r.missing_columns = [" or ".join(group) for group in missing]
            r.result_match = False
            r.match_mode = "rows ok, answer too thin"
            r.failure_category = r.failure_category or "THIN_ANSWER"
        elif not comparing_rows:
            # Nothing else is being compared for this turn, so meeting the
            # floor is the whole test.
            r.result_match, r.match_mode = True, "answer shape"

    if scoring:
        # A turn that answers correctly but misread the conversation is still a
        # defect: the next turn inherits the wrong state.
        if r.result_match and r.decision_match is False:
            r.result_match = False
            r.match_mode = "rows ok, context misread"

        sem = compare_semantics(turn.expected_sql or parsed.sql, parsed.sql, ordered=turn.ordered,
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
            # A column-only turn has no expected result to classify against,
            # and its failure is already named THIN_ANSWER.
            if comparing_rows:
                r.failure_category = _classify_failure(
                    r, expected, actual if actual is not None else expected
                )
            else:
                r.failure_category = r.failure_category or "THIN_ANSWER"
        elif not r.schema_grounded:
            r.failure_category = "HALLUCINATION"
        elif not r.semantic_match and comparing_rows:
            # Right rows, wrong query. Not counted against result accuracy, but
            # named so it cannot hide behind a passing row comparison.
            r.failure_category = "SEMANTIC_MISMATCH"
    else:
        r.result_match = None
        r.semantic_match = None
        # Absent ground truth is not absent error reporting. A query that never
        # ran is still a failure, and the branches of _classify_failure that
        # name one do not look at the expected result.
        #
        # A clarification is the exception. It has no SQL by design, and "no
        # SQL" is exactly what PROMPT_ERROR means -- so asked for revenue, the
        # model correctly answering that no such column exists was being
        # reported as having failed to answer at all.
        if r.clarification is not None:
            pass
        elif parsed.sql is None or not r.sql_valid or not r.execution_success:
            r.failure_category = _classify_failure(r, _NO_RESULT, _NO_RESULT)
        elif not r.schema_grounded:
            r.failure_category = "HALLUCINATION"

    # 4. Fold the turn into the state for whatever comes next. The state
    #    follows the SQL that was actually produced, so a wrong query is
    #    visible in the next turn's context rather than silently corrected.
    update_state(
        state,
        question,
        parsed.sql or turn.expected_sql,
        len(actual.rows) if actual is not None and actual.ok else None,
        entity,
        decision,
    )
    # After update_state, which is what sets the goal from the question that
    # opened the block. That default is right until a follow-up contradicts it
    # -- "open tasks for Sales" then "forget the department" leaves a goal
    # still naming Sales beside filters that no longer do. The model is the
    # only thing that can see the aim has moved, so its restatement wins.
    if followup_mode and r.restated_goal:
        state.active_goal = " ".join(r.restated_goal.split())
    # The recap is folded, not appended: the model is handed the previous one
    # and returns the whole thing rewritten, so it cannot grow. A rejected
    # recap leaves the previous one standing rather than blanking the thread.
    if followup_mode:
        accepted = accept_recap(r.recap)
        if accepted is not None:
            state.rolling_recap = accepted

    session.turns.append(Turn(index=turn.turn_index, question=question,
                              generated_sql=parsed.sql))

    _t = time.perf_counter()
    _attach_followup(
        r, turn, state,
        len(actual.rows) if actual is not None and actual.ok else None,
        followup_mode,
    )
    r.followup_ms = (time.perf_counter() - _t) * 1000
    r.latency_ms = (time.perf_counter() - started) * 1000
    return r


def logged(r: TurnResult) -> dict:
    """A turn as a log file keeps it: everything, but at most LOGGED_ROWS rows.

    A turn holds every row its query returned. A log that wrote them all would
    grow by thousands of rows per question, and it has never needed more than
    enough to read the answer back.
    """
    row = asdict(r)
    for key in ("actual_result", "expected_result"):
        row[key] = first_rows(row.get(key), LOGGED_ROWS)
    return row


def run_suite(
    conversations: list[Conversation],
    settings: Settings,
    mcp_config_path: Path,
    privacy_mode: str,
    jsonl_path: Path | None = None,
    on_result: Callable[[TurnResult], None] | None = None,
    context_mode: str = "state",
    followup_mode: bool = True,
) -> list[TurnResult]:
    if context_mode not in CONTEXT_MODES:
        raise ValueError(f"context_mode must be one of {CONTEXT_MODES}")
    # A suite has no session to resolve a caller from, and "my tasks" now
    # refuses rather than guessing -- correctly, but it would score every
    # MY_TASK question as a failure. The suite says who it is running as
    # instead, which is the same thing a request does, from a different source.
    identity = CallerIdentity(settings.benchmark_user_id,
                              settings.benchmark_user_name)
    gazetteer = load_gazetteer()
    log.info("gazetteer: %d entity value(s)", len(gazetteer))

    results: list[TurnResult] = []
    for conv in conversations:
        state = ConversationState()
        session = Session(session_id=conv.id, turns=[])
        for turn in conv.turns:
            r = run_turn(turn, state, gazetteer, settings,
                         mcp_config_path, privacy_mode, session,
                         context_mode=context_mode,
                         followup_mode=followup_mode,
                         identity=identity)
            results.append(r)

            if jsonl_path is not None:
                jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with jsonl_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(logged(r), default=str) + "\n")

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
