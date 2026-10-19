"""Where a chat lives after its turn: py_sql_chat and py_sql_chat_turn.

Ported from the Drupal port's ConversationStore and TurnOutcome. The tables
are copies of Drupal's -- sql_chat and sql_chat_turn, the same columns and
constraints (database/migrations/2026-10-19_chat_database.sql) -- under the py_
prefix, in the chat database (HISTORY_DATABASE_*), never the business one.
Every connection here is made with the HISTORY_DATABASE_USER login.

uid is the request's user_id. Every read and write is conditioned on it, so a
session id can only reach that user's own chats. Someone else's chat reads as
no chat at all.

Working state stays in the server's memory, as it stays in Drupal's
expiring key-value store. The recent questions and the recap are rebuilt from
the turns on every question, so a chat reopened after a restart still knows
what it was about.

Writes never fail a question: a history row that cannot be saved is logged and
dropped, as in Drupal.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime

import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row

from config.logging import get_logger
from pipeline.context import RECENT_QUESTIONS, ConversationState, _EXPLICIT_RESET

log = get_logger("chat_store")

# How much of a model response to keep when the whole one will not fit, and
# how much of that goes to its beginning.
RAW_OUTPUT_MAX = 8192
RAW_OUTPUT_HEAD = 6144
# A ceiling on the metadata blob, so one turn cannot bloat the table.
METADATA_MAX = 32768
# How long a chat title runs before it is clipped.
TITLE_MAX = 120
# How a chat's dates are shown: Drupal's 'd M y h:i A'.
DATE_FORMAT = "%d %b %y %I:%M %p"

# Statuses: what happened in the pipeline. Response types: what was seen.
SUCCESS = "success"
CLARIFICATION = "clarification"
NO_SQL = "no_sql"
UNSAFE_SQL = "unsafe_sql"
EXECUTION_FAILED = "execution_failed"
LLM_ERROR = "llm_error"


def turn_status(r) -> str:
    """What happened, from a turn result. Branch order matters: flags are
    False on paths that never set them."""
    # First: a clarification is correct but looks like several failures.
    if r.preflight_clarified or r.clarification is not None:
        return CLARIFICATION
    # A timeout counts as a provider failure; the detail stays in metadata.
    if r.generated_sql is None:
        return LLM_ERROR if (r.timed_out or r.error) else NO_SQL
    # Before the execution test: a refused statement never ran.
    if not r.sql_valid:
        return UNSAFE_SQL
    if not r.execution_success:
        return EXECUTION_FAILED
    # r.error alone is not a failure: it can be set on a turn that ran.
    return SUCCESS


def response_type(status: str) -> str:
    if status == SUCCESS:
        return "sql_result"
    if status == CLARIFICATION:
        return "clarification"
    return "error"


def effective_tokens(r) -> int:
    """What a turn cost: cache reads count at a tenth, as the debug panel
    counts them. Never negative: the column refuses it, and a failed insert
    loses the whole row."""
    prompt, cache_read, completion = r.prompt_tokens, r.cache_read_tokens, r.completion_tokens
    return max(0, round(prompt - cache_read + cache_read * 0.1 + completion))


def safe_session_id(session_id) -> str:
    """The session id, bounded and free of separators."""
    session_id = str(session_id or "").strip() or "default"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", session_id)[:64]


def state_array(state: ConversationState | None) -> dict | None:
    """The state as Drupal's ConversationState::toArray stores it: the same
    keys, so either implementation can read the other's rows."""
    if state is None:
        return None
    pending = state.pending_clarification
    return {
        "active_goal": state.active_goal,
        "active_subject": state.active_subject,
        "active_entity": state.active_entity,
        "active_tables": list(state.active_tables),
        "active_filters": dict(state.active_filters),
        "active_grouping": list(state.active_grouping),
        "active_sorting": state.active_sorting,
        "active_limit": state.active_limit,
        "last_intent": state.last_intent,
        "previous_sql": state.previous_sql,
        "previous_result_summary": state.previous_result_summary,
        "turns_in_block": state.turns_in_block,
        "pending_clarification": asdict(pending) if is_dataclass(pending) else pending,
        "pending_question": state.pending_question,
        "awaiting_answer_to": state.awaiting_answer_to,
        "rolling_recap": state.rolling_recap,
        "recent_questions": list(state.recent_questions),
    }


class ChatStore:
    """One user's chats."""

    def __init__(self, settings, uid: int | None):
        self.settings = settings
        self.uid = int(uid or 0)
        prefix = settings.chat_table_prefix
        self.chats = pgsql.Identifier(f"{prefix}sql_chat")
        self.turns = pgsql.Identifier(f"{prefix}sql_chat_turn")

    @property
    def enabled(self) -> bool:
        """A database and login of its own, and somebody to own the chats."""
        s = self.settings
        return bool(s.history_db_name and s.history_db_user) and self.uid > 0

    def _connect(self) -> psycopg.Connection:
        s = self.settings
        return psycopg.connect(host=s.history_db_host, port=s.history_db_port,
                               dbname=s.history_db_name, user=s.history_db_user,
                               password=s.history_db_password, connect_timeout=10)

    def reachable(self) -> bool:
        """Whether the chat login can read both chat tables."""
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(self._q("SELECT 1 FROM {chats} LIMIT 0"))
                cur.execute(self._q("SELECT 1 FROM {turns} LIMIT 0"))
            return True
        except Exception as exc:
            log.error("Chat database not reachable: %s", exc)
            return False

    def _q(self, text: str) -> pgsql.Composed:
        return pgsql.SQL(text).format(chats=self.chats, turns=self.turns)

    # ------------------------------------------------------------ write path

    def load(self, session_id) -> dict:
        """The chat's id, how many turns it has, and its history. A chat that
        cannot be loaded is an empty chat, not a failed question."""
        out = {"chat_id": None, "turn_index": 0,
               "history": {"questions": [], "recap": None}}
        if not self.enabled:
            return out
        try:
            with self._connect() as conn, conn.cursor() as cur:
                chat_id = self._chat_id(cur, session_id)
                if chat_id is not None:
                    # Counted, not stored: a counter column could disagree.
                    cur.execute(self._q("SELECT COUNT(*) FROM {turns} WHERE chat_id = %s"),
                                (chat_id,))
                    out["turn_index"] = int(cur.fetchone()[0])
                    out["history"] = self._history(cur, chat_id)
                out["chat_id"] = chat_id
        except Exception as exc:
            log.error("Could not load chat %s: %s", session_id, exc)
        return out

    def _history(self, cur, chat_id: int) -> dict:
        """The recent questions, oldest first, and the latest recap.

        The repaired or resumed question when there is one: a stored "4" means
        nothing without the question it answered. Questions stop at the latest
        explicit reset, which is kept.
        """
        cur.execute(self._q(
            "SELECT COALESCE(metadata->'pipeline'->>'normalized_question', question),"
            "       metadata->'pipeline'->>'context_reset',"
            "       CASE WHEN metadata->'state' IS NOT NULL THEN 1 ELSE 0 END,"
            "       metadata->'state'->>'rolling_recap'"
            " FROM {turns} WHERE chat_id = %s"
            f" ORDER BY sequence_number DESC LIMIT {int(RECENT_QUESTIONS)}"), (chat_id,))
        questions: list[str] = []
        recap, found = None, False
        for question, context_reset, has_state, row_recap in cur.fetchall():
            # The newest row that kept its state; a NULL there means forgotten.
            if not found and int(has_state) == 1:
                recap, found = row_recap, True
            questions.append(str(question or ""))
            if context_reset == "true" or _EXPLICIT_RESET.search(str(question or "")):
                break
        return {"questions": list(reversed(questions)), "recap": recap}

    def save(self, session_id, question: str = "") -> int | None:
        """Make sure the chat row exists, and move its clock. The question
        titles the chat on its first turn only. None if it could not be saved."""
        if not self.enabled:
            return None
        now = int(time.time())
        try:
            with self._connect() as conn, conn.cursor() as cur:
                chat_id = self._chat_id(cur, session_id)
                if chat_id is None:
                    cur.execute(self._q(
                        "INSERT INTO {chats} (uid, session_id, title, created_at, updated_at)"
                        " VALUES (%s, %s, %s, %s, %s) RETURNING id"),
                        (self.uid, safe_session_id(session_id), title_from(question), now, now))
                    return int(cur.fetchone()[0])
                # Later turns only move the clock; the title stays.
                cur.execute(self._q("UPDATE {chats} SET updated_at = %s WHERE id = %s AND uid = %s"),
                            (now, chat_id, self.uid))
                return chat_id
        except Exception as exc:
            # Swallowed: a history row is not worth a failed answer.
            log.error("Could not save chat %s: %s", session_id, exc)
            return None

    def record_turn(self, chat_id, turn_index: int, question: str, r, full: dict,
                    state: ConversationState | None = None) -> None:
        """One answered turn. Best-effort: any failure is logged and dropped."""
        if not self.enabled or not chat_id or int(chat_id) <= 0:
            return
        try:
            status = turn_status(r)
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(self._q(
                    "INSERT INTO {turns} (chat_id, sequence_number, question, generated_sql,"
                    " status, response_type, llm_response, llm_mode, llm_model,"
                    " effective_tokens, step_timings, metadata, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::json, %s::json, %s)"),
                    (int(chat_id),
                     # The pipeline counts turns from zero; a person from one.
                     int(turn_index) + 1,
                     str(question), r.generated_sql, status, response_type(status),
                     _llm_response(r, full, status),
                     _clip(r.llm_mode, 32), _clip(r.llm_model, 64),
                     effective_tokens(r), step_timings(r),
                     metadata_for(r, question, state), int(time.time())))
        except Exception as exc:
            log.error("Could not record turn %s of chat %s: %s", turn_index, chat_id, exc)

    # ------------------------------------------------------------- read path

    def list_chats(self, limit=50, offset=0) -> list[dict]:
        """This user's chats, most recently answered first."""
        limit = max(1, min(200, _int(limit, 50)))
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self._q(
                "SELECT c.id, c.title, c.created_at, c.updated_at,"
                " (SELECT COUNT(*) FROM {turns} t WHERE t.chat_id = c.id) AS turn_count"
                " FROM {chats} c WHERE c.uid = %s"
                " ORDER BY c.updated_at DESC, c.id DESC LIMIT %s OFFSET %s"),
                (self.uid, limit, max(0, _int(offset, 0))))
            return cur.fetchall()

    def count_chats(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._q("SELECT COUNT(*) FROM {chats} WHERE uid = %s"), (self.uid,))
            return int(cur.fetchone()[0])

    def open_chat(self, chat_id) -> dict | None:
        """One chat and its turns, or None if it is not this user's.

        Two statements, not a join: the turns are fetched by the id the
        ownership check returned, so no change can drop that check and still
        get rows.
        """
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self._q(
                "SELECT id, session_id, title, created_at, updated_at FROM {chats}"
                " WHERE id = %s AND uid = %s"), (_int(chat_id, 0), self.uid))
            chat = cur.fetchone()
            if chat is None:
                return None
            cur.execute(self._q("SELECT * FROM {turns} WHERE chat_id = %s ORDER BY sequence_number"),
                        (chat["id"],))
            return {"chat": chat, "turns": cur.fetchall()}

    def monthly_effective_tokens(self) -> int:
        """Effective tokens every user together has used this calendar month.

        No uid condition, unlike everything else here: the budget is shared.
        The month starts at 00:00 on the 1st, local time.
        """
        now = datetime.now().astimezone()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._q("SELECT COALESCE(SUM(effective_tokens), 0) FROM {turns}"
                                " WHERE created_at >= %s"), (int(start.timestamp()),))
            return int(cur.fetchone()[0])

    def _chat_id(self, cur, session_id) -> int | None:
        cur.execute(self._q("SELECT id FROM {chats} WHERE uid = %s AND session_id = %s"),
                    (self.uid, safe_session_id(session_id)))
        row = cur.fetchone()
        return None if row is None else int(row[0])


# ------------------------------------------------------------------ helpers

def title_from(question: str) -> str:
    """A chat's name, from the first thing asked in it, as typed."""
    title = " ".join(str(question or "").split())
    if len(title) <= TITLE_MAX:
        return title
    clipped = title[:TITLE_MAX]
    # Back up to a nearby word boundary; otherwise hard clip.
    space = clipped.rfind(" ")
    if space > TITLE_MAX - 20:
        clipped = clipped[:space]
    return clipped.rstrip(" ,.;:-") + "…"


def stamp(when: float | None) -> str | None:
    """A unix time a person can read, to the microsecond, in local time."""
    if not when:
        return None
    return datetime.fromtimestamp(float(when)).astimezone().isoformat(timespec="microseconds")


# Python measures named stages, not start and end times. Each keeps its own
# duration; the turn as a whole keeps its start and end.
_STAGES = (("normalize", "normalize_ms"), ("llm", "llm_wall_ms"),
           ("schema_check", "schema_check_ms"), ("safety", "safety_ms"),
           ("sql", "db_ms"), ("repair", "repair_ms"), ("followup", "followup_ms"))


def step_timings(r) -> str:
    """When this question started and finished, and what each step took."""
    started, total = float(r.turn_started or 0), float(r.latency_ms or 0)
    sql_ms = r.actual_result.get("duration_ms") if isinstance(r.actual_result, dict) else None
    return json.dumps({
        "started": stamp(started) if started > 0 else None,
        "ended": stamp(started + total / 1000) if started > 0 else None,
        "total_ms": round(total, 3),
        # The provider's own measure; steps.llm is the wall time around it.
        "llm_ms": round(float(r.llm_ms or 0), 3),
        "sql_ms": round(float(sql_ms), 3) if sql_ms is not None else round(float(r.db_ms or 0), 3),
        "steps": {name: {"start": None, "end": None, "ms": round(float(getattr(r, attr) or 0), 3)}
                  for name, attr in _STAGES if getattr(r, attr, 0)},
    })


def metadata_for(r, question: str, state: ConversationState | None = None) -> str:
    """Everything else worth keeping, as JSON, in Drupal's shape. Result rows
    and column names are never stored: shape and cost only."""
    result = r.actual_result if isinstance(r.actual_result, dict) else {}
    followup = r.followup if isinstance(r.followup, dict) else {}
    chart_result = getattr(r, "chart_result", None)
    normalized = str(r.normalized_question or "")
    metadata = {
        "llm": {"mode": r.llm_mode, "provider": r.llm_provider, "model": r.llm_model},
        "tokens": {"prompt": int(r.prompt_tokens), "cache_read": int(r.cache_read_tokens),
                   "cache_write": int(r.cache_write_tokens),
                   "completion": int(r.completion_tokens)},
        "pipeline": {
            "decision": str(r.decision or ""),
            "parse_strategy": str(r.parse_strategy or "none"),
            "preflight_clarified": bool(r.preflight_clarified),
            "resumed_from": r.resumed_from,
            "resumed_answering": r.resumed_answering,
            # Only when the repair layer actually changed the question.
            "normalized_question": normalized if normalized and normalized != question else None,
            "repairs": r.repairs or [],
            "context_chars": int(r.context_chars or 0),
            "tool_calls": int(r.tool_call_count or 0),
            "failure_category": str(r.failure_category or ""),
            "schema_grounded": bool(r.schema_grounded),
            "hallucinated": r.hallucinated or [],
            "sqlstate": r.sqlstate,
            # Unredacted, for debugging. Safe only because the read-only role
            # cannot read these tables.
            "raw_error": r.error,
            "timed_out": bool(r.timed_out),
            "context_reset": bool(r.context_reset),
            # No masquerade in a one-person console.
            "masqueraded": False,
            # Why a requested chart was not drawn ("ok" when it was), and how
            # long its own query took. None when no chart was asked for.
            "chart_reason": getattr(r, "chart_reason", None),
            "chart_query_ms": chart_result.get("duration_ms")
            if isinstance(chart_result, dict) else None,
        },
        # Shape, never content. None means no query ran, unlike 0.
        "result": {"row_count": int(result["row_count"]) if "row_count" in result else None,
                   "truncated": bool(result.get("truncated"))},
        "followup": {"type": str(followup.get("type") or "none"),
                     "question": str(followup.get("question") or ""),
                     "suggestions": followup.get("suggestions") or []},
    }
    if state is not None:
        metadata["state"] = state_array(state)
    if r.raw_output:
        metadata["raw_output"] = str(r.raw_output)

    # Degrade deterministically rather than risk a failed insert.
    encoded = _encode(metadata)
    if len(encoded) > METADATA_MAX and "raw_output" in metadata:
        metadata["raw_output"] = _clip_raw(metadata["raw_output"])
        encoded = _encode(metadata)
    if len(encoded) > METADATA_MAX:
        metadata.pop("raw_output", None)
        encoded = _encode(metadata)
    if len(encoded) > METADATA_MAX:
        metadata["followup"]["suggestions"] = []
        encoded = _encode(metadata)
    if len(encoded) > METADATA_MAX:
        # Shed last: it is the only part that could rebuild the thread.
        metadata.pop("state", None)
        encoded = _encode(metadata)
    return encoded


def _encode(value) -> str:
    try:
        # PHP's json_encode escapes "/" and non-ASCII; the database stores
        # what it is given, and both read back the same.
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": "metadata could not be encoded"})


def _clip_raw(raw: str) -> str:
    """Head and tail: how it started and how it ended both matter."""
    data = str(raw).encode("utf-8")
    if len(data) <= RAW_OUTPUT_MAX:
        return str(raw)
    tail = RAW_OUTPUT_MAX - RAW_OUTPUT_HEAD
    elided = len(data) - RAW_OUTPUT_MAX
    return (data[:RAW_OUTPUT_HEAD].decode("utf-8", "ignore")
            + f"\n…[{elided} bytes elided]…\n"
            + data[-tail:].decode("utf-8", "ignore"))


def _llm_response(r, full: dict, status: str):
    """What the person was told, when they were not shown a table."""
    if status == CLARIFICATION:
        return r.clarification
    if status == SUCCESS:
        return r.explanation
    # Already replaced, not scrubbed, by safe_error.
    return (full or {}).get("error")


def _clip(value, length: int):
    value = str(value or "").strip()
    return value[:length] or None


def _int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default

