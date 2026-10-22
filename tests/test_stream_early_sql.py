"""Handing over the rows before the answer has finished arriving.

The contract puts `sql` first in the reply object, and it is complete a mean
of 2.02 seconds before the last token -- the rest writes explanation, goal,
recap and next. Running the query in that gap is worth about two seconds to
whoever is waiting for a table.

What has to hold while it is:

  * the turn's own verdicts are what they were, because every accuracy figure
    in results/ was measured on them;
  * the query runs once, not twice -- a user's statement is not something to
    execute speculatively;
  * ungrounded SQL is still not executed. run_turn refuses it because the rows
    ARE the schema, and an early path running it would reopen that behind
    run_turn's back;
  * a clarification, which carries no SQL at all, finishes normally rather
    than waiting for a mark that never arrives.
"""

from __future__ import annotations

import pytest

from pipeline.context import ConversationState
from pipeline.lean_suite import SuiteTurn
from pipeline.models import ClaudeRun, Session
from pipeline.lean_runner import run_turn

pytestmark = pytest.mark.integration


class StreamingProvider:
    """Delivers a reply a few characters at a time, as a real one does."""

    def __init__(self, text, chunk=12):
        self.text = text
        self.chunk = chunk
        self.streamed = False

    def ask(self, question, mcp_config_path, privacy_mode, settings,
            session=None, on_delta=None):
        if on_delta is not None:
            self.streamed = True
            for i in range(0, len(self.text), self.chunk):
                on_delta(self.text[i:i + self.chunk])
        return ClaudeRun(ok=True, result_text=self.text, duration_ms=1.0,
                         prompt_tokens=100, completion_tokens=10)


def _turn(question):
    return SuiteTurn(id="ST01", question=question, expected_sql=None,
                     category="runtime", conversation_id="ST", turn_index=0)


def _run(monkeypatch, settings, reply, on_sql=None, question="how many?"):
    provider = StreamingProvider(reply)
    monkeypatch.setattr("pipeline.lean_runner.get_provider", lambda s: provider)
    result = run_turn(
        _turn(question), ConversationState(), settings,
        mcp_config_path=None, privacy_mode="strict",
        session=Session(session_id="st", turns=[]), on_sql=on_sql,
    )
    return result, provider


def _count_executions(monkeypatch):
    """Every statement the turn actually sends to the database."""
    from database import connection
    sent = []
    real = connection.run_readonly

    def counting(settings, sql, timeout_ms):
        sent.append(sql)
        return real(settings, sql, timeout_ms)

    monkeypatch.setattr("pipeline.lean_runner.run_readonly", counting)
    return sent


COUNT_SQL = '{"sql": "SELECT COUNT(*) FROM tms_initiative_flat", ' \
            '"explanation": "how many initiatives there are", ' \
            '"next": ["break it down by status", "show the newest ones"]}'


def test_the_rows_arrive_before_the_rest_of_the_answer(monkeypatch, settings):
    seen = []
    result, provider = _run(monkeypatch, settings, COUNT_SQL, on_sql=seen.append)

    assert provider.streamed, "the provider was never asked to stream"
    assert len(seen) == 1
    early = seen[0]
    assert early["generated_sql"] == "SELECT COUNT(*) FROM tms_initiative_flat"
    assert early["execution_success"] is True
    assert early["actual_result"]["rows"], "the early hand-over carried no rows"
    # And the turn still finished, with the parts that come after the SQL.
    assert result.explanation
    assert result.next_questions


def test_the_query_runs_once_and_not_twice(monkeypatch, settings):
    sent = _count_executions(monkeypatch)
    _run(monkeypatch, settings, COUNT_SQL, on_sql=lambda _: None)
    assert sent.count("SELECT COUNT(*) FROM tms_initiative_flat") == 1, (
        f"the statement was sent {len(sent)} time(s): {sent}")


def test_the_turn_reaches_the_same_verdicts_either_way(monkeypatch, settings):
    """Streaming is a latency change, so nothing it touches may differ."""
    streamed, _ = _run(monkeypatch, settings, COUNT_SQL, on_sql=lambda _: None)
    plain, _ = _run(monkeypatch, settings, COUNT_SQL, on_sql=None)

    for field in ("generated_sql", "sql_valid", "execution_success",
                  "schema_grounded", "clarification", "explanation",
                  "decision", "failure_category"):
        assert getattr(streamed, field) == getattr(plain, field), field
    assert streamed.actual_result == plain.actual_result


def test_a_clarification_never_hands_over_rows(monkeypatch, settings):
    seen = []
    reply = ('{"clarify": "which department did you mean?", '
             '"options": ["the one that owns it", "the one working on it"]}')
    result, provider = _run(monkeypatch, settings, reply, on_sql=seen.append)

    assert provider.streamed
    assert seen == [], "a reply with no SQL handed over rows anyway"
    assert result.clarification
    assert result.generated_sql is None


def test_ungrounded_sql_is_not_executed_early(monkeypatch, settings):
    """The leak run_turn's grounding gate exists to stop.

    Answering "what columns does that table have" out of information_schema
    returns the schema AS ROWS, where no guard on the wording can reach it.
    An early execution that skipped the check would reopen it.
    """
    sent = _count_executions(monkeypatch)
    seen = []
    reply = ('{"sql": "SELECT column_name FROM information_schema.columns", '
             '"explanation": "the columns"}')
    result, _ = _run(monkeypatch, settings, reply, on_sql=seen.append)

    assert seen == [], "ungrounded SQL was executed and its rows handed over"
    assert not any("information_schema" in s for s in sent)
    assert result.schema_grounded is False


def test_a_provider_that_cannot_stream_still_answers(monkeypatch, settings):
    """on_delta is offered, never required."""

    class Unstreaming:
        def ask(self, question, mcp_config_path, privacy_mode, settings,
                session=None, on_delta=None):
            return ClaudeRun(ok=True, result_text=COUNT_SQL, duration_ms=1.0)

    monkeypatch.setattr("pipeline.lean_runner.get_provider", lambda s: Unstreaming())
    seen = []
    result = run_turn(
        _turn("how many?"), ConversationState(), settings,
        mcp_config_path=None, privacy_mode="strict",
        session=Session(session_id="st", turns=[]), on_sql=seen.append,
    )
    assert seen == []
    assert result.generated_sql == "SELECT COUNT(*) FROM tms_initiative_flat"
    assert result.execution_success is True
