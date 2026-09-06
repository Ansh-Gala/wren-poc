"""Running a turn with no known-correct answer.

The benchmark always has an expected_sql to compare against. A real user does
not, and the QA console asks real questions -- so the same pipeline has to run
when there is nothing to score against.

Reusing run_turn rather than writing a second path is the whole point. Two
pipelines would drift, and the console exists to show what the benchmarked
system actually does.
"""

from __future__ import annotations

import pytest

from benchmark.context import ConversationState
from benchmark.lean_suite import SuiteTurn
from benchmark.models import ClaudeRun, Session
from benchmark.lean_runner import run_turn

pytestmark = pytest.mark.integration


class FakeProvider:
    """Returns a fixed reply, so the pipeline runs without the CLI."""

    def __init__(self, text):
        self.text = text
        self.asked = []

    def ask(self, question, mcp_config_path, privacy_mode, settings, session=None):
        self.asked.append(question)
        return ClaudeRun(ok=True, result_text=self.text, duration_ms=1.0,
                         prompt_tokens=100, completion_tokens=10)


def _turn(question, **kw):
    return SuiteTurn(
        id="RT01", question=question, expected_sql=None, category="runtime",
        conversation_id="RT", turn_index=0, **kw,
    )


def _run(monkeypatch, settings, reply, question="How many business objects are there?",
         state=None):
    provider = FakeProvider(reply)
    monkeypatch.setattr("benchmark.lean_runner.get_provider", lambda s: provider)
    return run_turn(
        _turn(question), state or ConversationState(), [], settings,
        mcp_config_path=None, privacy_mode="strict",
        session=Session(session_id="rt", turns=[]),
    ), provider


def test_a_turn_with_no_expected_sql_still_executes_the_query(monkeypatch, settings):
    """The generated query must run and return rows, with nothing to compare to."""
    result, _ = _run(
        monkeypatch, settings,
        '{"sql": "SELECT COUNT(*) FROM tms_business_object_flat"}',
    )

    assert result.generated_sql == "SELECT COUNT(*) FROM tms_business_object_flat"
    assert result.sql_valid is True
    assert result.execution_success is True
    assert result.actual_result["row_count"] == 1
    assert result.actual_result["rows"][0][0] == 307


def test_scoring_is_not_applicable_rather_than_failed(monkeypatch, settings):
    """No ground truth means no verdict -- which is not the same as a wrong one.

    Left as False, every runtime turn would look like a failure and would be
    given a failure_category naming a defect that was never observed.
    """
    result, _ = _run(
        monkeypatch, settings,
        '{"sql": "SELECT COUNT(*) FROM tms_business_object_flat"}',
    )

    assert result.result_match is None
    assert result.semantic_match is None
    assert result.failure_category == ""


def test_a_broken_query_is_still_reported_as_broken(monkeypatch, settings):
    """Absent ground truth must not mean absent error reporting."""
    result, _ = _run(
        monkeypatch, settings,
        '{"sql": "SELECT nonexistent_column FROM tms_business_object_flat"}',
    )

    assert result.execution_success is False
    assert result.error is not None
    assert result.failure_category == "SCHEMA_ERROR"


def test_the_follow_up_layer_still_runs(monkeypatch, settings):
    """Repair, classification and suggestions do not depend on ground truth."""
    result, provider = _run(
        monkeypatch, settings,
        '{"sql": "SELECT business_object_id FROM tms_business_object_flat '
        "WHERE business_object_type = 'AR_YD_Suiting'\"}",
        question="show the AR_YD_Suiting itmes",
    )

    assert [r["corrected"] for r in result.repairs] == ["items"]
    assert provider.asked == ["show the AR_YD_Suiting items"], "model saw the repair"
    assert result.followup_type == "exploration"
    assert result.followup["suggestions"]


def test_a_clarification_at_runtime_is_not_a_failure(monkeypatch, settings):
    """Asking which of three types was meant is the system working, not failing.

    The preflight branch scored itself against expect_behavior, which defaults
    to "sql". A real question carries no expectation at all, so a perfectly
    correct clarification came back as SHOULD_NOT_HAVE_CLARIFIED with
    result_match False -- the console would have painted its own best
    behaviour red.
    """
    from benchmark.lean_runner import load_gazetteer

    provider = FakeProvider("unused: preflight answers before the model is asked")
    monkeypatch.setattr("benchmark.lean_runner.get_provider", lambda s: provider)

    result = run_turn(
        _turn("Show the AR_YD items"), ConversationState(), load_gazetteer(),
        settings, mcp_config_path=None, privacy_mode="strict",
        session=Session(session_id="rt", turns=[]),
    )

    assert result.preflight_clarified is True
    assert result.followup_type == "clarification"
    assert provider.asked == [], "the model should never have been called"

    assert result.failure_category == ""
    assert result.result_match is None
    assert result.semantic_match is None


def test_the_model_asking_a_question_is_not_a_failed_turn(monkeypatch, settings):
    """A clarification has no SQL, and "no SQL" is what PROMPT_ERROR means.

    Asked for revenue the model correctly replies that no such column exists.
    With no expected answer to compare against, the absence of SQL was read as
    the model having failed to produce any, and a correct refusal was labelled
    PROMPT_ERROR.
    """
    result, _ = _run(
        monkeypatch, settings,
        '{"clarify": "The schema has no revenue column, so there is no way to '
        'compute that."}',
        question="What is the total revenue?",
    )

    assert result.generated_sql is None
    assert result.clarification.startswith("The schema has no revenue column")
    assert result.failure_category == ""
    assert result.followup_type == "clarification"
