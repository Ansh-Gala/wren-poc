"""The shape of what the server sends: one turn's response, the state
snapshot, the chart and the PII debug block."""

from __future__ import annotations

from pipeline.chart_check import build as build_chart, note as chart_note_for
from pipeline.context import ConversationState
from pipeline.evaluator import SHOWN_ROWS, first_rows
from pipeline.freshness import freshness_note
from pipeline.initiative import with_row_colour
from pipeline.labels import with_column_labels, with_presentation
from pipeline.lean_runner import TurnResult
from pipeline.links import with_links
from pipeline.metadata import profile
from pipeline.pii import PiiError, PiiGuard
from pipeline.redact import names_a_database_object, safe_error, safe_explanation

from server.config import DISPLAYED

# ------------------------------------------------------------ state shape --

def state_snapshot(state: ConversationState) -> dict:
    """The conversation state as the console's right-hand rail renders it.
    The keys of Drupal's ConversationState::snapshot."""
    return {
        "goal": state.active_goal,
        "subject": state.active_subject,
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
    built = build_chart(chart, source, source.get("column_labels") or [], profile().colours())
    drawn = built["chart"]
    if drawn is not None and "title" in drawn and names_a_database_object(drawn["title"]):
        drawn = {k: v for k, v in drawn.items() if k != "title"}
    return drawn, built["reason"], built.get("note") or chart_note_for(built["reason"])


def _no_chart(reason: str) -> tuple[None, str, str | None]:
    return None, reason, chart_note_for(reason)


def pretty_sql(sql: str | None) -> str | None:
    """`sql` laid out to be read: a clause per line, nested queries indented.
    Display only. What runs, and what is stored, is the statement as written."""
    if not sql:
        return sql
    try:
        import sqlglot

        return ";\n\n".join(sqlglot.transpile(sql, read="postgres", write="postgres",
                                              pretty=True))
    except Exception:
        return sql


def pii_debug(r: TurnResult, pii: PiiGuard | None, settings) -> dict:
    """What aliasing did on this turn, for the debug pane.

    It holds the real values -- the mapping and the SQL as it ran -- so it is
    a debug field like the SQL itself: public_response leaves it out, and
    debug is honoured only on this machine. Never stored with the turn.
    """
    if pii is None:
        return {"enabled": False}
    new = {e["alias"] for e in pii.vault.new}
    seen = " ".join(filter(None, [r.normalized_question, r.generated_sql]))
    executed = None
    if r.generated_sql:
        try:
            executed = pii.restore_sql(r.generated_sql)
        except PiiError as exc:
            executed = f"-- not run: {exc}"
    return {
        "enabled": True,
        "model": settings.pii_model,
        "threshold": settings.pii_threshold,
        "detect_ms": round(r.pii_ms, 1),
        "sent_to_llm": r.normalized_question,
        "aliases": [{**e, "new": e["alias"] in new, "used": e["alias"] in seen}
                    for e in pii.vault.entries()],
        "masked": r.pii_masked,
        "generated_sql": r.generated_sql,
        "executed_sql": executed,
        "executed_sql_pretty": pretty_sql(executed),
    }


def displayed(full: dict, pii: PiiGuard) -> dict:
    """The response with the real values back in everything the model wrote
    that a reader sees. The SQL stays as generated: debug shows that."""
    out = {**full, **{key: pii.restore_deep(full[key]) for key in DISPLAYED if key in full}}
    result = out.get("result")
    if isinstance(result, dict) and isinstance(result.get("chart"), dict):
        out["result"] = {**result, "chart": pii.restore_deep(result["chart"])}
    return out


def shown_result(actual_result, settings) -> dict | None:
    """The rows a reader is shown, with the fields the grid reads beside them.

    At most SHOWN_ROWS rows; row_count keeps the whole count. with_row_colour
    and with_links are innermost: both need the real column names, and every
    wrapper around them only adds fields.
    """
    shown = first_rows(actual_result, SHOWN_ROWS)
    columns = (shown or {}).get("columns")
    return with_column_labels(with_links(with_row_colour(shown, columns, settings), columns))


def with_freshness(result, settings, ran: list) -> dict | None:
    """The "not live" note, when rows came back from a table that lags."""
    if isinstance(result, dict) and result.get("rows") and settings is not None:
        note = freshness_note(settings, ran)
        if note:
            return {**result, "freshness": note}
    return result


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

    result = with_presentation(shown_result(r.actual_result, settings),
                               after.get("tables"), r.grouped)
    chart, chart_reason, chart_note = chart_for(r, result)
    if isinstance(result, dict) and chart is not None:
        result = {**result, "chart": chart}
    if isinstance(result, dict) and chart_note is not None:
        result = {**result, "chart_note": chart_note}
    # Read from the SQL that ran, the chart's own included.
    ran = [r.generated_sql]
    if chart is not None and isinstance(r.chart, dict):
        ran.append(r.chart.get("sql") or "")
    result = with_freshness(result, settings, ran)
    chart_query = r.chart_result if isinstance(r.chart_result, dict) else None

    return {
        "decision": r.decision,
        "question": asked,
        "normalized_question": r.normalized_question,
        "repairs": r.repairs,
        "resumed_from": r.resumed_from,
        "resumed_answering": r.resumed_answering,

        # Written before the query runs: on an error it would describe an
        # answer that never arrived, so it is dropped.
        "explanation": safe_explanation(r.explanation) if error is None else None,
        # Public: a filter the reader cannot see, they cannot argue with.
        "context": pills or [],

        "generated_sql": r.generated_sql,
        "generated_sql_pretty": pretty_sql(r.generated_sql),
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
