"""Serve the pipeline over HTTP, so the QA console can ask real questions.

    python scripts/serve_api.py
    python scripts/serve_api.py --port 8000 --context-mode state

Then open http://localhost:8000/ -- the console is served from here too, which
keeps it same-origin and means there is no CORS to think about.

There is no second pipeline. Every request goes through pipeline.lean_runner
.run_turn, the same function the four benchmark suites run, with no expected
SQL to compare against. That is the whole design: a console that exercised its
own copy of the logic would drift from the thing being measured, and would
then be showing you something other than what the benchmark says.

Deliberately no web framework. This is a local debugging tool for one person
at a time, and http.server is in the standard library, so the dependency list
stays as short as the rest of the project's.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import _bootstrap  # noqa: F401

from pipeline.chart_check import build as build_chart, note as chart_note_for
from pipeline.chat_store import CLARIFICATION, DATE_FORMAT, SUCCESS, ChatStore
from pipeline.context import ConversationState, remember_question
from pipeline.context_pills import context_pills, drop_by_ref
from pipeline.evaluator import SHOWN_ROWS, first_rows
from pipeline.followup import ACTION_TYPES, Action, apply_action, label_for_ref
from pipeline.freshness import freshness_note
from pipeline.identity_provider import resolve_identity
from pipeline.lean_runner import TurnResult, load_gazetteer, logged, run_turn
from pipeline.initiative import with_initiative
from pipeline.links import with_links
from pipeline.labels import with_column_labels, with_presentation
from pipeline.lean_suite import SuiteTurn
from pipeline.metadata import enable_site_metadata
from pipeline.models import Session
from pipeline.redact import (
    GENERIC, names_a_database_object, public_response, safe_error, safe_explanation,
)
from config.logging import get_logger, register_secrets
from config.settings import load_settings
from llm_api.factory import llm_identity

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"

# How many turns of debug detail a conversation keeps for later inspection.
DEBUG_LOG_TURNS = 50

log = get_logger("serve_api")

# All users together have used this month's budget (MONTHLY_TOKEN_LIMIT).
# The sentence and the code are Drupal's TokenLimitException's; HTTP 429.
TOKEN_LIMIT_MESSAGE = ("You have exceeded your monthly token limit. "
                       "Please try again next month.")
TOKEN_LIMIT_CODE = "monthly_token_limit"

# Drupal's ChatRuntime::LOCK_WAIT: a second question on a busy chat waits
# this long for the first, then fails rather than queueing forever.
LOCK_WAIT_SECONDS = 30


class TokenLimitError(Exception):
    pass


# --------------------------------------------------------------- sessions --

class Conversation:
    """One thread: its state, its transcript, and a lock.

    The lock matters because a turn takes seconds and mutates the state in
    place. Two overlapping requests on one session would interleave a repair,
    a classification and a state update, and the resulting context would belong
    to neither turn.
    """

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.state = ConversationState()
        self.session = Session(session_id=session_id, turns=[])
        self.lock = threading.Lock()
        self.turn_index = 0
        # Full responses for recent turns, so switching debug on can fill in
        # answers already on screen without re-running anything. Kept here
        # rather than sent and hidden: with debug off the SQL must not reach
        # the browser at all, which is the whole point of the switch.
        self.debug_log: list[dict] = []

    def reset(self) -> None:
        self.state = ConversationState()
        self.session = Session(session_id=self.id, turns=[])
        self.turn_index = 0
        self.debug_log.clear()


SESSIONS: dict[str, Conversation] = {}
SESSIONS_LOCK = threading.Lock()


def conversation_for(session_id: str) -> Conversation:
    with SESSIONS_LOCK:
        if session_id not in SESSIONS:
            SESSIONS[session_id] = Conversation(session_id)
        return SESSIONS[session_id]


# ------------------------------------------------------------ state shape --

def state_snapshot(state: ConversationState) -> dict:
    """The conversation state as the console's right-hand rail renders it.
    The keys of Drupal's ConversationState::snapshot."""
    return {
        "goal": state.active_goal,
        "subject": state.active_subject,
        "entity": state.active_entity,
        "tables": list(state.active_tables),
        "filters": dict(state.active_filters),
        "grouping": list(state.active_grouping),
        "sorting": state.active_sorting,
        "limit": state.active_limit,
        "intent": state.last_intent,
        "previous_sql": state.previous_sql,
        "turns_in_block": state.turns_in_block,
        "pending_question": state.pending_question or None,
    }


def state_mutations(before: dict, after: dict) -> list[str]:
    """What this turn changed, in the words the rail uses.

    Computed by diffing rather than by recording as we go: the state is
    rewritten from the SQL that actually ran, so a claim about what changed is
    only trustworthy if it is read back off the result.
    """
    out: list[str] = []

    if before.get("entity") != after.get("entity"):
        out.append(f"subject {before.get('entity') or 'none'} -> "
                   f"{after.get('entity') or 'none'}")

    old_filters, new_filters = before.get("filters") or {}, after.get("filters") or {}
    for column in new_filters:
        if column not in old_filters:
            out.append(f"+ filter {new_filters[column]}")
        elif old_filters[column] != new_filters[column]:
            out.append(f"~ filter {old_filters[column]} -> {new_filters[column]}")
    for column in old_filters:
        if column not in new_filters:
            out.append(f"- filter {old_filters[column]}")

    for key, label in (("grouping", "grouped by"), ("sorting", "sorted by"),
                       ("limit", "limit"), ("intent", "intent")):
        if before.get(key) != after.get(key):
            out.append(f"{label} {before.get(key) or 'none'} -> "
                       f"{after.get(key) or 'none'}")

    return out


def chart_for(r: TurnResult, result) -> tuple[dict | None, str | None, str | None]:
    """The chart for this answer, why there is none when there is none, and
    what the reader is told. Ported from the Drupal port's ChatRuntime.

    The shown rows are the source unless the model wrote a chart query. If
    that query failed there is no chart: never a fallback to the main rows,
    whose shape and meaning may differ from what was asked to be drawn.
    """
    chart = r.chart
    if not isinstance(chart, dict):
        return None, None, None
    if "invalid" in chart:
        return _no_chart("config_" + chart["invalid"])
    if not r.execution_success or not (result or {}).get("rows"):
        return _no_chart("no_answer")
    if "sql" in chart:
        if r.chart_error:
            return _no_chart("chart_sql_" + r.chart_error)
        if not isinstance(r.chart_result, dict):
            return _no_chart("chart_sql_not_run")
        source = with_column_labels(r.chart_result)
    else:
        source = result
    built = build_chart(chart, source, source.get("column_labels") or [])
    drawn = built["chart"]
    if drawn is not None and "title" in drawn and names_a_database_object(drawn["title"]):
        drawn = {k: v for k, v in drawn.items() if k != "title"}
    return drawn, built["reason"], built.get("note") or chart_note_for(built["reason"])


def _no_chart(reason: str) -> tuple[None, str, str | None]:
    return None, reason, chart_note_for(reason)


def to_response(r: TurnResult, asked: str, before: dict, after: dict,
                settings=None, pills: list[dict] | None = None) -> dict:
    """TurnResult -> the contract documented at the top of ui/api.js.

    result_match and semantic_match come through as None, which the console
    renders as "n/a". They are only meaningful against a known-correct answer,
    and a real question does not have one.
    """
    # The raw message names the table and column it failed on. The sanitised
    # one is what a normal answer carries; the original travels only under
    # debug, alongside the SQL it belongs to.
    error = safe_error(r.error, getattr(r, "sqlstate", None))

    # At most SHOWN_ROWS rows; row_count keeps the whole count. with_initiative
    # and with_links are innermost: both need the real column names, and every
    # wrapper around them only adds fields.
    shown = first_rows(r.actual_result, SHOWN_ROWS)
    columns = (shown or {}).get("columns")
    result = with_presentation(
        with_column_labels(with_links(with_initiative(shown, columns, settings), columns)),
        after.get("tables"), r.grouped)
    chart, chart_reason, chart_note = chart_for(r, result)
    if isinstance(result, dict) and chart is not None:
        result = {**result, "chart": chart}
    if isinstance(result, dict) and chart_note is not None:
        result = {**result, "chart_note": chart_note}
    if isinstance(result, dict) and result.get("rows") and settings is not None:
        # Read from the SQL that ran, the chart's own included.
        ran = [r.generated_sql]
        if chart is not None and isinstance(r.chart, dict):
            ran.append(r.chart.get("sql") or "")
        note = freshness_note(settings, ran)
        if note:
            result = {**result, "freshness": note}
    chart_query = r.chart_result if isinstance(r.chart_result, dict) else None

    return {
        "decision": r.decision,
        "question": asked,
        "normalized_question": r.normalized_question,
        "repairs": r.repairs,
        "resumed_from": r.resumed_from,
        "resumed_answering": r.resumed_answering,
        "preflight_clarified": r.preflight_clarified,

        # Written before the query runs: on an error it would describe an
        # answer that never arrived, so it is dropped.
        "explanation": safe_explanation(r.explanation) if error is None else None,
        # Public: a filter the reader cannot see, they cannot argue with.
        "context": pills or [],

        "generated_sql": r.generated_sql,
        "sql_valid": r.sql_valid,
        "execution_success": r.execution_success,
        "error": error,
        "raw_error": r.error,
        "failure_category": r.failure_category,
        "result": result,
        # Debug only: why there is no chart, and the chart's own query. Never
        # the chart query's rows; only the built chart carries any of them.
        "chart_reason": chart_reason,
        "chart_sql": r.chart.get("sql") if isinstance(r.chart, dict) else None,
        "chart_query": None if chart_query is None else {
            "columns": chart_query.get("columns", []),
            "types": chart_query.get("types", []),
            "row_count": chart_query.get("row_count"),
            "duration_ms": chart_query.get("duration_ms"),
        },

        "semantic_match": r.semantic_match,
        "semantic_issues": r.semantic_issues,
        "projection_verdict": r.projection_verdict,
        "result_match": r.result_match,
        "schema_grounded": r.schema_grounded,
        "hallucinated": r.hallucinated,

        "clarification": r.clarification,
        "followup": r.followup or {"type": "none", "suggestions": []},

        "state": after,
        "state_mutations": state_mutations(before, after),

        # Debug only. Grouped: a model id means something only with its mode
        # and provider.
        "llm": {"mode": r.llm_mode, "provider": r.llm_provider, "model": r.llm_model},
        "tokens": {
            "prompt": r.prompt_tokens,
            "cache_read": r.cache_read_tokens,
            "cache_write": r.cache_write_tokens,
            "completion": r.completion_tokens,
        },
        "latency_ms": r.latency_ms,
        "tool_calls": r.tool_call_count,
        "context_chars": r.context_chars,
        "raw_output": r.raw_output,
    }


# ------------------------------------------------------------------ asking --

def provider_problem(settings) -> str | None:
    """Why the configured LLM cannot answer, or None when it can."""
    # The transports Drupal offers: the local CLI, or one HTTPS call to an
    # API. An API needs only its key; the CLI needs to be installed.
    keys = {"anthropic": ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            "openai": ("OPENAI_API_KEY", settings.openai_api_key),
            "groq": ("GROQ_API_KEY", settings.openai_api_key),
            "gemini": ("GEMINI_API_KEY", settings.openai_api_key)}
    provider = settings.llm_provider
    if provider in keys:
        name, key = keys[provider]
        return None if key else f"LLM_PROVIDER is {provider!r} but {name} is not set in .env."
    if provider != "cli":
        return f"LLM_PROVIDER is {provider!r}. Use cli, anthropic, openai, groq or gemini."
    from llm_api.cli_provider import detect_claude
    if not detect_claude(settings.claude_command):
        return (f"Claude Code CLI not found (looked for {settings.claude_command!r} "
                "on PATH).\nInstall it from https://claude.com/claude-code, then "
                "run `claude --version` to confirm.")
    return None


def health(settings) -> dict:
    """GET /health, in the shape of Drupal's /api/sql-chat/health."""
    from database.connection import read_only_posture, run_readonly
    mode, vendor, model = llm_identity(settings)
    database = run_readonly(settings, "SELECT 1")
    posture = read_only_posture(settings)
    ready = provider_problem(settings) is None
    return {
        "ok": database.ok and ready and posture["select_only"],
        "provider": mode,
        # What is answering questions right now.
        "api_provider": vendor if mode == "api" else None,
        "model": model,
        "provider_ready": ready,
        "database": {
            "ok": database.ok,
            "name": settings.pg_database,
            # Sanitised: the raw message can name schema objects.
            "error": None if database.ok else "could not query the database",
        },
        "read_only_role": {
            "role": settings.pg_readonly_user,
            "privileges": posture["privileges"],
            "select_only": posture["select_only"],
        },
    }


def preflight(settings) -> None:
    """Fail at startup rather than three seconds into someone's first question.

    A misconfigured provider surfaces as an HTTP 500 carrying whatever the
    upstream said, which is a poor place to learn that .env still points at a
    model that was decommissioned. Checked once, here, where the message can
    say what to do about it.
    """
    problem = provider_problem(settings)
    if problem:
        raise SystemExit(problem)
    if settings.llm_provider == "anthropic":
        return

    if not settings.cli_lean:
        # The MCP path needs wren_setup, which a lean-only deployment does not
        # ship. Checked here so the answer arrives at startup with something
        # actionable in it, rather than as a ModuleNotFoundError on the first
        # question that mentions no module the reader has heard of.
        try:
            import wren_setup.mcp_config  # noqa: F401
        except ModuleNotFoundError:
            raise SystemExit(
                "CLI_LEAN is false, which selects the MCP path, but wren_setup "
                "is not installed in this checkout.\n"
                "This is a production deployment: it ships only the lean path. "
                "Set CLI_LEAN=true in .env.\n"
                "The MCP path lives on the develop branch."
            )
        # Not fatal there -- the MCP path works -- but it is almost never what
        # is wanted, and the difference is invisible until the token figures
        # come back three times larger.
        log.warning("CLI_LEAN is not set: using the MCP path, which needs "
                    "`wren serve mcp` running and costs ~3x the context. "
                    "Set CLI_LEAN=true for the mode the benchmarks used.")


class Runtime:
    """Everything a request needs that does not change between requests."""

    def __init__(self, args) -> None:
        self.settings = load_settings()
        register_secrets(self.settings.secrets())
        preflight(self.settings)
        self.gazetteer = load_gazetteer()
        # Lean mode makes no MCP calls, so there is nothing to configure and
        # no wren_setup to import. Writing the file anyway was harmless but it
        # made the module a hard dependency of a path that never uses it.
        self.mcp_config_path = None
        if not self.settings.cli_lean:
            from wren_setup.mcp_config import write_mcp_config
            self.mcp_config_path = write_mcp_config(
                args.config, args.privacy, self.settings)
        self.privacy = args.privacy
        self.context_mode = args.context_mode

        # Questions people actually type are the only source of test cases
        # nobody thought to write, and they were previously going to stderr and
        # dying with the terminal. Same filename the suites use, so
        # scripts/analyze_followup.py reads a console session unchanged.
        self.log_path = None
        if args.log:
            self.log_path = Path(args.log) / "raw" / "turns.jsonl"
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_lock = threading.Lock()

        # Boot the warm Claude processes now rather than on the first
        # question. Each needs about three seconds before it can answer, and
        # the server is normally started well before anyone types anything --
        # so the cost lands in dead time instead of on the first arrival.
        if (self.settings.llm_provider == "cli" and self.settings.cli_lean
                and self.settings.cli_pool_size > 0):
            from claude.prompts import build_lean_system_prompt
            from llm_api.cli_provider import _pool_for
            _pool_for(self.settings, build_lean_system_prompt())

    def record(self, result, question: str, state: dict) -> None:
        if self.log_path is None:
            return
        row = logged(result)
        row.update({
            "asked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session_id": result.conversation_id,
            "typed": question,
            "state_after": state,
        })
        try:
            with self.log_lock, self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except OSError as exc:      # a full disk must not lose the answer
            log.warning("could not append to %s: %s", self.log_path, exc)

    def ask(self, payload: dict, on_rows: Callable[[dict], None] | None = None) -> dict:
        """One turn, and the response the console renders.

        ``on_rows`` is optional. When it is given, the reply is streamed and
        the table is handed over the moment the SQL is complete -- about two
        seconds before the last token. The returned response is the same
        either way, so a caller that ignores the rows behaves exactly as it
        does today.
        """
        question = str(payload.get("question") or "").strip()
        drop_ref = str(payload.get("drop_ref") or "").strip()
        # A drop has no question; the goal fills it in once the state is in
        # hand. Checked again below.
        if not question and not drop_ref:
            raise ValueError("question is required")
        debug = bool(payload.get("debug"))
        session_id = payload.get("session_id") or "default"
        store = ChatStore(self.settings, self.settings.chatbot_user_id)

        # Before the state is touched: a refused question costs nothing and
        # never enters the recent-questions window.
        self.assert_within_monthly_limit(store)

        conversation = conversation_for(session_id)

        if not conversation.lock.acquire(timeout=LOCK_WAIT_SECONDS):
            raise RuntimeError("another question is still being answered on this session")
        try:
            reset = bool(payload.get("reset_context"))
            if reset:
                conversation.reset()

            # The recent questions and the recap come from the chat's turns,
            # not from memory, so a chat reopened after a restart still knows
            # what it was about. On a reset this turn is the new start. The
            # turn number is counted from the rows, so it continues them.
            loaded = store.load(session_id)
            if loaded["chat_id"] is not None:
                conversation.turn_index = loaded["turn_index"]
                state = conversation.state
                state.recent_questions = []
                state.rolling_recap = None
                if not reset:
                    for asked in loaded["history"]["questions"]:
                        remember_question(state, asked)
                    state.rolling_recap = loaded["history"]["recap"]

            # A clicked suggestion carries a structured action. Applying it
            # here means the context the model sees already reflects the
            # choice; the label still goes through as the question, so the
            # turn takes the ordinary path and there is no second way for a
            # query to be built.
            action = payload.get("action")
            if action and action.get("type") in ACTION_TYPES:
                try:
                    apply_action(conversation.state, Action(
                        type=action["type"],
                        field=action.get("field"),
                        operator=action.get("operator"),
                        value=action.get("value"),
                    ))
                except (ValueError, TypeError) as exc:
                    log.warning("ignoring unusable action %s: %s", action, exc)

            # Map a chip's ref back to the exact offered wording. A stale chip
            # matches nothing and is read as typed text; the turn still
            # resolves it, the same as a typed answer.
            option_ref = str(payload.get("option_ref") or "").strip()
            if option_ref:
                chosen = label_for_ref(conversation.state.pending_clarification, option_ref)
                if chosen is not None:
                    question = chosen

            # Dropping a pill: take the constraint off, and ask the active goal
            # again with one fewer constraint.
            if drop_ref:
                dropped = drop_by_ref(conversation.state, drop_ref)
                if dropped and not question and conversation.state.active_goal is not None:
                    question = conversation.state.active_goal
            if not question:
                raise ValueError("question is required")

            before = state_snapshot(conversation.state)

            turn_index = conversation.turn_index
            turn = SuiteTurn(
                id=f"{conversation.id}.{conversation.turn_index}",
                question=question,
                expected_sql=None,          # no ground truth: this is a real question
                category="runtime",
                conversation_id=conversation.id,
                turn_index=conversation.turn_index,
            )
            result = run_turn(
                turn, conversation.state, self.gazetteer, self.settings,
                self.mcp_config_path, self.privacy, conversation.session,
                context_mode=self.context_mode,
                on_sql=(lambda early: on_rows(self.rows_event(early, debug)))
                if on_rows else None,
                # Every turn: the business rules, not this code, decide what
                # is personal. A cached lookup is cheap.
                identity=resolve_identity(self.settings, self.settings.chatbot_user_id),
            )
            if reset:
                result.context_reset = True
            conversation.turn_index += 1
            after = state_snapshot(conversation.state)
            pills = context_pills(conversation.state)
            self.record(result, question, after)
            full = to_response(result, question, before, after, self.settings, pills)
            # The chart's verdict is reached in to_response, after the turn ran.
            result.chart_reason = full.get("chart_reason")

            # Inside the lock: the next question reads its recent questions
            # from these rows, and must not load before this one lands.
            chat_id = store.save(session_id, question)
            # Lets the page ask for every row. Only now: the chat id does not
            # exist until save().
            if chat_id is not None and isinstance(full.get("result"), dict) \
                    and full["result"].get("truncated"):
                full["result"] = {**full["result"],
                                  "download": {"chat_id": chat_id, "turn": turn_index + 1}}
            store.record_turn(chat_id, turn_index, question, result, full, conversation.state)
        finally:
            conversation.lock.release()

        log.info("  %-10s %-22s %s", result.decision,
                 result.failure_category or result.followup_type, question[:48])
        if debug and store.enabled:
            # After the turn is recorded, so the figure includes this question.
            usage = self.token_usage(store)
            if usage is not None:
                full["token_usage"] = usage

        # Bounded: a long session should not grow without limit, and nobody
        # scrolls back past fifty answers to read their SQL. Under the lock
        # because /debug reads this list from another thread.
        with conversation.lock:
            conversation.debug_log.append({**full, "turn_index": turn_index})
            del conversation.debug_log[:-DEBUG_LOG_TURNS]
        # Debug off is the default, and it is enforced here rather than in the
        # page: a field the browser receives has already left the server.
        return full if debug else public_response(full)

    def assert_within_monthly_limit(self, store: ChatStore) -> None:
        """Refuse when all users together have reached this month's limit.

        A usage figure that cannot be read lets the question through: a broken
        counter must not take the chatbot down. The last question allowed can
        go over by its own cost, which is only known once it has run.
        """
        limit = self.settings.monthly_token_limit
        if limit == 0 or not store.enabled:
            return
        try:
            used = store.monthly_effective_tokens()
        except Exception as exc:
            log.error("Monthly token usage could not be read, so the question "
                      "was allowed: %s", exc)
            return
        if used >= limit:
            raise TokenLimitError(TOKEN_LIMIT_MESSAGE)

    def token_usage(self, store: ChatStore) -> dict | None:
        """This month's usage, for the debug badge. A limit of 0 is none."""
        try:
            return {"used": store.monthly_effective_tokens(),
                    "limit": self.settings.monthly_token_limit}
        except Exception:
            return None

    def rows_event(self, early: dict, debug: bool) -> dict:
        """The table, before the sentences that explain it have been written.

        Redacted by the same public_response the finished answer goes through
        -- whitelisting, so the SQL and the real column names drop out with
        debug off exactly as they do there. A second redaction rule here is a
        second thing to keep in step.

        with_presentation is the one wrapper missing, and deliberately: what
        it needs is the model's `group` verdict, which has not arrived yet.
        Grouping lands with the finished answer, which carries the whole
        result again.
        """
        summary = first_rows(early.get("actual_result"), SHOWN_ROWS)
        columns = (summary or {}).get("columns")
        result = with_column_labels(
            with_links(with_initiative(summary, columns, self.settings), columns))
        # The same note the answer will carry, so it arrives with the table.
        if isinstance(result, dict) and result.get("rows"):
            note = freshness_note(self.settings, [early.get("generated_sql")])
            if note:
                result = {**result, "freshness": note}
        event = {
            "generated_sql": early.get("generated_sql"),
            "sql_valid": early.get("sql_valid"),
            "execution_success": early.get("execution_success"),
            "error": safe_error(early.get("error"), early.get("sqlstate")),
            "raw_error": early.get("error"),
            "result": result,
        }
        return event if debug else public_response(event)


# ------------------------------------------------------------- saved chats --

def chat_dates(row: dict) -> dict:
    """Both forms of a chat's dates: formatted to read, and a timestamp for
    "2 hours ago". Drupal's d M y h:i A."""
    out = {}
    for key in ("created_at", "updated_at"):
        ts = int(row.get(key) or 0)
        out[key] = time.strftime(DATE_FORMAT, time.localtime(ts))
        out[f"{key}_ts"] = ts
    return out


def present_chats(store: ChatStore, limit, offset) -> dict:
    """GET /chats -- this user's chats, newest activity first. Drupal's
    ChatsResource. The placeholder title is presentation only."""
    chats = [{"id": int(row["id"]),
              "title": row["title"] or "Untitled chat",
              "turn_count": int(row["turn_count"]),
              **chat_dates(row)}
             for row in store.list_chats(limit, offset)]
    return {"chats": chats, "total": store.count_chats()}


def _inert_followup(followup) -> dict:
    """A replayed clarification with its chips made unclickable: a ref ties a
    chip to an outstanding clarification, and a transcript has none."""
    if not isinstance(followup, dict) or not followup.get("suggestions"):
        return followup if isinstance(followup, dict) else {}
    return {**followup, "suggestions": [{k: v for k, v in s.items() if k != "ref"}
                                        for s in followup["suggestions"] if isinstance(s, dict)]}


def present_chat(opened: dict, debug: bool) -> dict:
    """GET /chats/<id> -- one thread, reopened: its turns in order, without
    the rows, which are never stored. Drupal's ChatResource::present; each
    turn goes through public_response, the one audited whitelist."""
    turns = []
    for row in opened["turns"]:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        clarifying = row["status"] == CLARIFICATION
        succeeded = row["status"] == SUCCESS
        result = metadata.get("result") or {}
        shaped = {
            "question": row["question"],
            "clarification": row["llm_response"] if clarifying else None,
            # Stored raw, so guarded here as on the live path.
            "explanation": safe_explanation(row["llm_response"]) if succeeded else None,
            # Already passed through safe_error when stored.
            "error": None if (clarifying or succeeded) else row["llm_response"],
            "followup": _inert_followup(metadata.get("followup") or {}),
            "result": {"row_count": result.get("row_count"),
                       "truncated": bool(result.get("truncated")),
                       # Rows are never stored.
                       "rows": []},
        }
        turn = {**public_response(shaped),
                "sequence_number": int(row["sequence_number"]),
                # Safe to expose: neither names a table, column or statement.
                "status": row["status"],
                "response_type": row["response_type"],
                "created_at": time.strftime(DATE_FORMAT, time.localtime(int(row["created_at"]))),
                "created_at_ts": int(row["created_at"])}
        if debug:
            timings = row.get("step_timings") or {}
            turn["generated_sql"] = row["generated_sql"]
            turn["step_timings"] = json.loads(timings) if isinstance(timings, str) else timings
            turn["metadata"] = metadata
        turns.append(turn)

    chat = opened["chat"]
    return {"chat": {"id": int(chat["id"]),
                     # Lets the page keep asking in a reopened chat.
                     "session_id": chat["session_id"],
                     "title": chat["title"] or "Untitled chat",
                     "turn_count": len(turns),
                     **chat_dates(chat)},
            "turns": turns}


# What a refused stored query is told. Never the SQL.
CSV_REFUSED = "This answer cannot be downloaded."


def csv_cell(value) -> str:
    """One value as CSV text. Text Excel would run as a formula gets a leading
    quote; numbers, negative ones included, stay as they are."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text and not _is_number(text) and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def full_csv(settings, store: ChatStore, chat_id, turn) -> tuple[int, dict | bytes]:
    """GET /chats/<id>/turns/<n>/csv -- every row of one answered question.

    Drupal's CsvController. The question's stored SQL runs again, through the
    gates the answer passed, with no row cut. Someone else's chat is a 404.
    Returns (status, JSON body) or (200, the CSV's bytes).
    """
    opened = store.open_chat(chat_id) if store.enabled else None
    if opened is None:
        return 404, {"error": "No such chat."}
    sql = ""
    for row in opened["turns"]:
        if int(row["sequence_number"]) == int(turn) and row["status"] == SUCCESS:
            sql = str(row["generated_sql"] or "").strip()
    if not sql:
        return 404, {"error": "No such answer."}

    # It passed these once, but it is read back from a table, not from the
    # turn that checked it.
    from pipeline.safety import UnsafeSQLError, assert_read_only
    from pipeline.sql_semantics import check_against_schema
    try:
        assert_read_only(sql)
    except UnsafeSQLError:
        return 422, {"error": CSV_REFUSED}
    if not check_against_schema(sql).grounded:
        return 422, {"error": CSV_REFUSED}

    from database.connection import run_readonly
    from pipeline.labels import column_labels
    result = run_readonly(settings, sql)
    if result.error:
        # Log, not wire: the raw message names tables and columns.
        log.error("Full CSV for chat %s question %s failed: %s", chat_id, turn, result.error)
        return 500, {"error": safe_error(result.error, result.sqlstate)}

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(column_labels(result.columns))
    for row in result.rows:
        writer.writerow([csv_cell(v) for v in row])
    # A BOM, so Excel reads the file as UTF-8.
    return 200, ("﻿" + out.getvalue()).encode("utf-8")


# ------------------------------------------------------------------- http --

# The console is a tool for one person on their own machine. /debug and the
# debug flag hand back the SQL and the real column names, so they answer only
# a caller on this machine, even when --host exposes the rest.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})


def _local_client(address: str) -> bool:
    return address in _LOOPBACK


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime = None          # set in main()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # quieter than the default
        pass

    # No CORS headers. The console is served from here, so it is same-origin;
    # "Access-Control-Allow-Origin: *" let any web page the user had open
    # read this server's answers.

    def _local(self) -> bool:
        return _local_client(self.client_address[0])

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _stream(self) -> None:
        """POST /ask/stream -- the table first, the rest when it is written.

        Two Server-Sent Events:

            event: rows      the query and what it returned
            event: answer    exactly what POST /ask returns

        `rows` is omitted when the turn clarifies, because a clarification
        carries no SQL and none is coming. `answer` always arrives and is the
        whole response, so a client may ignore `rows` entirely and behave as
        it does today -- which is what keeps this additive rather than a
        second contract to maintain.

        Connection: close rather than chunked. The body's length is not known
        when the headers go out, and closing the connection to end the stream
        is the older and simpler of the two ways to say so.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": f"bad request body: {exc}"})
        if isinstance(payload, dict) and not self._local():
            payload["debug"] = False

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(event: str, data: dict) -> None:
            body = json.dumps(data, default=str)
            self.wfile.write(f"event: {event}\ndata: {body}\n\n".encode("utf-8"))
            self.wfile.flush()

        # Kill switch, honoured server-side: when off, only `answer` is sent.
        streaming = self.runtime.settings.stream_answers
        try:
            answer = self.runtime.ask(payload, on_rows=(lambda d: emit("rows", d))
                                      if streaming else None)
            emit("answer", answer)
        except TokenLimitError as exc:
            # Same body as /ask's 429.
            emit("error", {"error": str(exc), "code": TOKEN_LIMIT_CODE})
        except ValueError as exc:
            emit("error", {"error": str(exc)})
        except Exception as exc:                  # a bad turn must not kill the server
            # Log, not wire: the raw message names tables and columns.
            log.exception("streamed turn failed")
            emit("error", {"error": GENERIC})

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/health":
            return self._json(200, health(self.runtime.settings))

        if path == "/chats" or path.startswith("/chats/"):
            return self._chats(path, parse_qs(query))

        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (UI_DIR / name).resolve()
        # Nothing outside ui/ is servable, whatever the path says.
        if not str(target).startswith(str(UI_DIR.resolve())) or not target.is_file():
            return self._json(404, {"error": f"no such file: {name}"})

        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")   # it is being edited
        self.end_headers()
        self.wfile.write(body)

    def _chats(self, path: str, query: dict) -> None:
        """The saved chats: the list, one chat, and one answer's full CSV."""
        settings = self.runtime.settings
        store = ChatStore(settings, settings.chatbot_user_id)
        first = lambda key, default: (query.get(key) or [default])[0]
        try:
            if path == "/chats":
                if not store.enabled:
                    return self._json(200, {"chats": [], "total": 0})
                return self._json(200, present_chats(store, first("limit", 50),
                                                     first("offset", 0)))

            match = re.fullmatch(r"/chats/(\d+)/turns/(\d+)/csv", path)
            if match:
                chat_id, turn = int(match.group(1)), int(match.group(2))
                status, body = full_csv(settings, store, chat_id, turn)
                if status != 200:
                    return self._json(status, body)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="chat-{chat_id}-answer-{turn}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, private")
                self.end_headers()
                self.wfile.write(body)
                return None

            match = re.fullmatch(r"/chats/(\d+)", path)
            if match:
                opened = store.open_chat(match.group(1)) if store.enabled else None
                # Someone else's chat is a 404, never a 403: the endpoint does
                # not confirm that an id exists.
                if opened is None:
                    return self._json(404, {"error": "No such chat."})
                debug = bool(first("debug", "")) and self._local()
                return self._json(200, present_chat(opened, debug))
        except Exception:
            # Log, not wire, as on /ask.
            log.exception("saved chats failed on %s", path)
            return self._json(500, {"error": "I couldn't load your chat history."})
        return self._json(404, {"error": "no such chat path"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        if path == "/debug":
            # What the server kept for turns it has already answered. Reads
            # only; nothing is generated and nothing is executed. It holds the
            # SQL and the real column names, so only this machine may ask.
            if not self._local():
                return self._json(403, {"error": "/debug answers only on this machine"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": f"bad request body: {exc}"})
            conversation = conversation_for(payload.get("session_id") or "default")
            with conversation.lock:
                return self._json(200, {"turns": list(conversation.debug_log)})

        if path == "/ask/stream":
            return self._stream()

        if path != "/ask":
            return self._json(404, {"error": "POST /ask"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": f"bad request body: {exc}"})
        if isinstance(payload, dict) and not self._local():
            payload["debug"] = False

        try:
            return self._json(200, self.runtime.ask(payload))
        except TokenLimitError as exc:
            return self._json(429, {"error": str(exc), "code": TOKEN_LIMIT_CODE})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:                      # a bad turn must not kill the server
            # Log, not wire: the raw message names tables and columns.
            log.exception("turn failed")
            return self._json(500, {"error": GENERIC})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default="D")
    ap.add_argument("--privacy", default="strict")
    ap.add_argument("--context-mode", default="state",
                    choices=["none", "history", "state"])
    ap.add_argument("--log", default="logs/console",
                    help="directory to append every turn to as JSONL; "
                         "'' disables logging")
    args = ap.parse_args()

    # Before Runtime: it builds the system prompt for the warm pool.
    enable_site_metadata()
    Handler.runtime = Runtime(args)
    settings = Handler.runtime.settings
    mode = "lean (no MCP)" if settings.cli_lean else f"MCP config {args.config}"

    print(f"provider: {settings.llm_provider} / {settings.claude_model or 'default'}   {mode}")
    print(f"database: {settings.pg_database}   context mode: {args.context_mode}")
    user = resolve_identity(settings, settings.chatbot_user_id)
    print(f"user: {user.user_id} {user.display_name}" if user else
          "user: nobody (set CHATBOT_USER_ID in .env to answer 'my tasks')")
    print(f"gazetteer: {len(Handler.runtime.gazetteer)} entity value(s)")
    print()
    print(f"  console   http://{args.host}:{args.port}/")
    print(f"  endpoint  POST http://{args.host}:{args.port}/ask")
    if Handler.runtime.log_path:
        print(f"  log       {Handler.runtime.log_path}")
    print()
    print("Ctrl+C to stop.")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
        # Warm processes are children of this one; without this they outlive
        # a Ctrl+C and sit holding memory.
        from llm_api.cli_provider import shutdown_pools
        shutdown_pools()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
