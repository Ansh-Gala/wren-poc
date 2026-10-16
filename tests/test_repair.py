"""One more attempt, when the database says what is wrong.

Postgres names the fault precisely -- "DISTINCT is not implemented for window
functions", "column x does not exist" -- and that sentence used to be read,
sanitised for the user, and thrown away. The model that wrote the query never
learned it had written something impossible.

Measured on the question that prompted this: three runs in five produced
COUNT(DISTINCT ...) OVER (...), which Postgres has never implemented.

What has to hold while a second attempt exists:

  * one attempt, never a loop -- a bad question must not become an unbounded
    bill, and a second failure is a signal worth showing;
  * the corrected statement goes through the same grounding and safety gates,
    so a repair cannot become the way round them;
  * a repair that fails leaves the original failure standing, because that is
    the one the user's question actually produced;
  * a turn that succeeded first time never reaches any of this.
"""

from __future__ import annotations

import pytest

from pipeline.context import ConversationState
from pipeline.lean_suite import SuiteTurn
from pipeline.models import ClaudeRun, Session
from pipeline.lean_runner import run_turn

pytestmark = pytest.mark.integration


GOOD = '{"sql": "SELECT COUNT(*) FROM tms_initiative_flat"}'
# Valid SQL, real columns, and Postgres refuses it: DISTINCT is not
# implemented for window functions. Exactly the shape that started this.
WINDOW_DISTINCT = (
    '{"sql": "SELECT COUNT(DISTINCT initiative_id) OVER (PARTITION BY '
    'workflow_code) AS n FROM tms_initiative_flat"}'
)
UNGROUNDED = '{"sql": "SELECT column_name FROM information_schema.columns"}'
UNSAFE = '{"sql": "SELECT * FROM pg_catalog.pg_tables"}'


class Scripted:
    """Answers with each reply in turn, and counts how often it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked = []

    def ask(self, question, mcp_config_path, privacy_mode, settings,
            session=None, on_delta=None):
        self.asked.append(question)
        text = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return ClaudeRun(ok=True, result_text=text, duration_ms=1.0)


def _run(monkeypatch, settings, *replies, repair_mode=True):
    provider = Scripted(*replies)
    monkeypatch.setattr("pipeline.lean_runner.get_provider", lambda s: provider)
    turn = SuiteTurn(id="RP01", question="how many per workflow?",
                     expected_sql=None, category="runtime",
                     conversation_id="RP", turn_index=0)
    result = run_turn(
        turn, ConversationState(), [], settings, mcp_config_path=None,
        privacy_mode="strict", session=Session(session_id="rp", turns=[]),
        repair_mode=repair_mode,
    )
    return result, provider


def test_a_rejected_query_is_tried_once_more(settings, monkeypatch):
    result, provider = _run(monkeypatch, settings, WINDOW_DISTINCT, GOOD)

    assert result.repair_attempted
    assert result.repair_succeeded
    assert result.execution_success
    assert result.generated_sql == "SELECT COUNT(*) FROM tms_initiative_flat"
    # The statement that failed is kept, so a run can be read afterwards.
    assert "OVER" in result.repaired_from


def test_the_model_is_told_what_the_database_said(settings, monkeypatch):
    _, provider = _run(monkeypatch, settings, WINDOW_DISTINCT, GOOD)

    assert len(provider.asked) == 2
    second = provider.asked[1]
    assert "DISTINCT is not implemented for window functions" in second
    # And what it asked, or the correction answers the error and loses the
    # question.
    assert "how many per workflow?" in second


def test_one_attempt_and_no_more(settings, monkeypatch):
    # Both replies fail. A loop would ask a third time.
    result, provider = _run(monkeypatch, settings, WINDOW_DISTINCT, WINDOW_DISTINCT)

    assert len(provider.asked) == 2
    assert result.repair_attempted
    assert not result.repair_succeeded


def test_a_failed_repair_leaves_the_original_failure_standing(settings, monkeypatch):
    result, _ = _run(monkeypatch, settings, WINDOW_DISTINCT, WINDOW_DISTINCT)

    assert not result.execution_success
    assert "window function" in (result.error or "")
    # Not rewritten to the repair's SQL: the reported failure must be the one
    # the user's question produced.
    assert "OVER" in (result.generated_sql or "")


def test_a_repair_cannot_get_round_the_grounding_gate(settings, monkeypatch):
    """The leak docs/gotchas.md section 11 exists to stop.

    A repair that returned information_schema would have its rows shown --
    and the rows ARE the schema.
    """
    result, _ = _run(monkeypatch, settings, WINDOW_DISTINCT, UNGROUNDED)

    assert not result.repair_succeeded
    assert "information_schema" not in (result.generated_sql or "")


def test_a_repair_cannot_get_round_the_safety_gate(settings, monkeypatch):
    result, _ = _run(monkeypatch, settings, WINDOW_DISTINCT, UNSAFE)

    assert not result.repair_succeeded
    assert "pg_catalog" not in (result.generated_sql or "")


def test_a_working_query_is_never_repaired(settings, monkeypatch):
    result, provider = _run(monkeypatch, settings, GOOD)

    assert len(provider.asked) == 1, "a successful turn asked the model twice"
    assert not result.repair_attempted
    assert result.repair_ms == 0.0


def test_repair_can_be_turned_off(settings, monkeypatch):
    result, provider = _run(monkeypatch, settings, WINDOW_DISTINCT, GOOD,
                            repair_mode=False)

    assert len(provider.asked) == 1
    assert not result.repair_attempted
    assert not result.execution_success


def test_an_identical_reply_is_not_run_again(settings, monkeypatch):
    """A repair that changes nothing has repaired nothing.

    Running it would fail the same way for the same reason, and cost another
    round trip to find that out.
    """
    result, provider = _run(monkeypatch, settings, WINDOW_DISTINCT, WINDOW_DISTINCT)
    assert not result.repair_succeeded
    assert result.repaired_from is None


# Another statement Postgres refuses, so a repair that runs and fails again.
WINDOW_DISTINCT_TOO = (
    '{"sql": "SELECT COUNT(DISTINCT workflow_code) OVER () AS n '
    'FROM tms_initiative_flat"}'
)


class Costed(Scripted):
    """Scripted, and every call costs the same tokens."""

    def ask(self, *args, **kwargs):
        run = super().ask(*args, **kwargs)
        run.prompt_tokens, run.completion_tokens = 100, 10
        run.cache_read_tokens, run.cache_write_tokens = 50, 5
        return run


def test_a_failed_repair_still_counts_its_tokens(settings, monkeypatch):
    """Drupal's monthly limit counts the retry; a failed one still cost."""
    monkeypatch.setattr("pipeline.lean_runner.get_provider",
                        lambda s: Costed(WINDOW_DISTINCT, WINDOW_DISTINCT_TOO))
    turn = SuiteTurn(id="RP02", question="how many per workflow?",
                     expected_sql=None, category="runtime",
                     conversation_id="RP", turn_index=0)
    result = run_turn(turn, ConversationState(), [], settings, mcp_config_path=None,
                      privacy_mode="strict", session=Session(session_id="rp2", turns=[]))

    assert result.repair_attempted and not result.repair_succeeded
    assert (result.prompt_tokens, result.completion_tokens) == (200, 20)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (100, 10)


def test_a_repair_that_fails_again_names_no_repaired_from(settings, monkeypatch):
    """repaired_from says a repair replaced the query. This one did not."""
    result, _ = _run(monkeypatch, settings, WINDOW_DISTINCT, WINDOW_DISTINCT_TOO)
    assert not result.repair_succeeded
    assert result.repaired_from is None
    assert "OVER (PARTITION BY" in (result.generated_sql or "")


def test_a_repair_that_raises_leaves_the_original_failure(settings, monkeypatch):
    class Breaks(Scripted):
        def ask(self, *args, **kwargs):
            if self.asked:
                raise RuntimeError("the provider fell over")
            return super().ask(*args, **kwargs)

    monkeypatch.setattr("pipeline.lean_runner.get_provider",
                        lambda s: Breaks(WINDOW_DISTINCT))
    turn = SuiteTurn(id="RP03", question="how many per workflow?",
                     expected_sql=None, category="runtime",
                     conversation_id="RP", turn_index=0)
    result = run_turn(turn, ConversationState(), [], settings, mcp_config_path=None,
                      privacy_mode="strict", session=Session(session_id="rp3", turns=[]))

    assert result.repair_attempted and not result.repair_succeeded
    assert not result.execution_success
    assert "window function" in (result.error or "")
