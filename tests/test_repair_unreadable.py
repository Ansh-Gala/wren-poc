"""The edge cases where Python read a turn differently from Drupal.

No database: the query runner is replaced by one that records what it was
given, which is also how the unreadable statement is shown never to run.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from config.settings import Settings
from pipeline import lean_runner
from pipeline.context import ConversationState
from pipeline.evaluator import normalize_value
from pipeline.lean_runner import _reads_as_zero, run_turn
from pipeline.lean_suite import SuiteTurn
from pipeline.models import ClaudeRun, QueryResult, Session

GOOD = "SELECT COUNT(*) FROM tms_initiative_flat"
UNREADABLE = "SELECT COUNT(*) FROM tms_initiative_flat WHERE ("
SETTINGS = Settings(pg_host="h", pg_port=5432, pg_database="d", pg_user="u",
                    cli_lean=True)


class Scripted:
    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    def ask(self, question, mcp_config_path, privacy_mode, settings,
            session=None, on_delta=None):
        self.asked.append(question)
        text = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return ClaudeRun(ok=True, result_text=text, duration_ms=1.0)


@pytest.fixture
def ran(monkeypatch):
    seen: list[str] = []

    def execute(settings, sql, timeout_ms, memo=None):
        seen.append(sql)
        return QueryResult(columns=["count"], rows=[(7,)], duration_ms=1.0)

    monkeypatch.setattr(lean_runner, "_execute", execute)
    return seen


def _run(monkeypatch, *sqls, repair_mode=True):
    provider = Scripted(*[f'{{"sql": "{s}"}}' for s in sqls])
    monkeypatch.setattr("pipeline.lean_runner.get_provider", lambda s: provider)
    turn = SuiteTurn(id="UR01", question="how many initiatives?", expected_sql=None,
                     category="runtime", conversation_id="UR", turn_index=0)
    result = run_turn(turn, ConversationState(), [], SETTINGS, mcp_config_path=None,
                      privacy_mode="strict", session=Session(session_id="ur", turns=[]),
                      repair_mode=repair_mode)
    return result, provider


def test_unreadable_sql_is_repaired_and_never_run(monkeypatch, ran):
    result, provider = _run(monkeypatch, UNREADABLE, GOOD)

    assert ran == [GOOD]
    assert "could not parse SQL" in provider.asked[1]
    assert result.repair_attempted and result.repair_succeeded
    assert result.sql_valid and result.execution_success and result.error is None
    assert (result.generated_sql, result.repaired_from) == (GOOD, UNREADABLE)


def test_a_repair_that_is_still_unreadable_leaves_the_refusal(monkeypatch, ran):
    result, provider = _run(monkeypatch, UNREADABLE, UNREADABLE + " (")

    assert ran == [] and len(provider.asked) == 2
    assert not result.sql_valid and not result.repair_succeeded
    assert "could not parse" in result.error and result.repaired_from is None


def test_a_refusal_for_safety_is_not_repaired(monkeypatch, ran):
    result, provider = _run(monkeypatch, "DELETE FROM tms_initiative_flat", GOOD)

    assert ran == [] and len(provider.asked) == 1
    assert not result.repair_attempted


def test_with_repair_off_unreadable_sql_is_only_refused(monkeypatch, ran):
    result, provider = _run(monkeypatch, UNREADABLE, GOOD, repair_mode=False)

    assert ran == [] and len(provider.asked) == 1 and not result.sql_valid


@pytest.mark.parametrize("value,zero", [
    (0, True), ("0", True), (Decimal("0"), True), (0.0, True),
    (Decimal("0.00"), False), (-0.0, False), ("0.00", False), (False, False),
    (1, False), (None, False), (" 0", False),
])
def test_zero_reads_as_drupal_reads_it(value, zero):
    assert _reads_as_zero(value) is zero


def test_only_a_utc_or_zoneless_midnight_is_a_plain_date():
    assert normalize_value(datetime(2026, 6, 1)) == "2026-06-01"
    assert normalize_value(datetime(2026, 6, 1, tzinfo=timezone.utc)) == "2026-06-01"
    kolkata = timezone(timedelta(hours=5, minutes=30))
    assert normalize_value(datetime(2026, 6, 1, tzinfo=kolkata)) != "2026-06-01"
    assert normalize_value(datetime(2026, 6, 1, 0, 0, 1)) == "2026-06-01 00:00:01"
    assert normalize_value(date(2026, 6, 1)) == "2026-06-01"
