"""Saved chats as the console shows them, and an answer's full CSV."""

from __future__ import annotations

import csv
import io
import json
import time

from config.logging import get_logger
from pipeline.chat_store import CLARIFICATION, ChatStore, DATE_FORMAT, SUCCESS
from pipeline.evaluator import pg_text
from pipeline.initiative import colours_by_lookup, indices as initiative_indices
from pipeline.metadata import profile
from pipeline.pii import (
    AliasRefused,
    PiiError,
    PiiVault,
    restore_deep,
    restore_sql,
    stored_aliases,
)
from pipeline.redact import public_response, safe_error, safe_explanation

from server.services.runtime import welcome

log = get_logger("serve_api")


# ------------------------------------------------------------- saved chats --

UNTITLED = "Untitled chat"


def formatted_date(ts) -> str:
    """Drupal's d M y h:i A, in local time."""
    return time.strftime(DATE_FORMAT, time.localtime(int(ts or 0)))


def chat_dates(row: dict) -> dict:
    """Both forms of a chat's dates: formatted to read, and a timestamp for
    "2 hours ago"."""
    out = {}
    for key in ("created_at", "updated_at"):
        out[key] = formatted_date(row.get(key))
        out[f"{key}_ts"] = int(row.get(key) or 0)
    return out


def present_chats(store: ChatStore, limit, offset) -> dict:
    """GET /chats -- this user's chats, newest activity first. Drupal's
    ChatsResource. The placeholder title is presentation only."""
    chats = [{"id": int(row["id"]),
              "title": row["title"] or UNTITLED,
              "turn_count": int(row["turn_count"]),
              **chat_dates(row)}
             for row in store.list_chats(limit, offset)]
    return {"chats": chats, "total": store.count_chats(), "welcome": welcome()}


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
    # What the model wrote was stored with aliases; the reader sees values.
    vault = stored_vault(opened["turns"])
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
        if vault is not None:
            shaped = restore_deep(shaped, vault)
        turn = {**public_response(shaped),
                "sequence_number": int(row["sequence_number"]),
                # Safe to expose: neither names a table, column or statement.
                "status": row["status"],
                "response_type": row["response_type"],
                "created_at": formatted_date(row["created_at"]),
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
                     "title": chat["title"] or UNTITLED,
                     "turn_count": len(turns),
                     **chat_dates(chat)},
            "turns": turns}


def stored_vault(turns: list[dict]) -> PiiVault | None:
    """A saved chat's aliases, from its turns. None when they contradict each
    other, which a reader of the chat must not paper over."""
    try:
        return PiiVault.from_entries(stored_aliases(row.get("metadata") for row in turns))
    except PiiError as exc:
        log.error("A saved chat's aliases are unusable: %s", exc)
        return None


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


def csv_colour_names(result, settings) -> dict:
    """Each row's colour name ("Green"), keyed by initiative id.

    The grid draws a colour strip from colours_by_lookup when the answer has
    an initiative id but no colour column; this is that strip as text. Empty
    when the answer has its own colour column, or no colours. Drupal's
    CsvController::colourNames.
    """
    where = initiative_indices(result.columns)
    if where["colour"] is not None:
        return {}
    name_by_code = {str(colour["code"]): str(name)[:1].upper() + str(name)[1:]
                    for name, colour in profile().colours().items()
                    if isinstance(colour, dict) and "code" in colour}
    found = colours_by_lookup({"rows": result.rows}, where, settings)
    return {record_id: name_by_code.get(code, "") for record_id, code in found.items()}


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
    # Stored as the model wrote it, aliases and all: the values go back in
    # here, from the aliases the chat's turns stored, as they did when it ran.
    vault = stored_vault(opened["turns"])
    if vault is None:
        return 422, {"error": CSV_REFUSED}
    if not vault.empty:
        try:
            sql = restore_sql(sql, vault)
        except AliasRefused:
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
    headings = column_labels(result.columns)
    colours = csv_colour_names(result, settings)
    if colours:
        headings = ["Colour", *headings]
    id_at = initiative_indices(result.columns)["id"]
    types = result.types or []
    writer.writerow(headings)
    for row in result.rows:
        # The database's own text, as Drupal's PDO hands it to fputcsv.
        cells = [csv_cell(pg_text(v, types[i] if i < len(types) else ""))
                 for i, v in enumerate(row)]
        if colours:
            record_id = row[id_at] if id_at < len(row) else None
            cells.insert(0, "" if record_id is None else colours.get(str(record_id), ""))
        writer.writerow(cells)
    # A BOM, so Excel reads the file as UTF-8.
    return 200, ("﻿" + out.getvalue()).encode("utf-8")
