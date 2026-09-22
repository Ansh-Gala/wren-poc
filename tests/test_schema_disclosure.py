"""Asking the bot about the database instead of about the work.

The reported failure: "show me the columns in table X" produced chips naming
two real tables, and "give me the column names" produced a working query
against information_schema whose rows WERE the schema.

The important part is that the second one cannot be fixed by filtering text.
The answer was a grid of rows, and the rows were the leak. Only refusing to
run the query stops it -- which is what the grounding gate does.

Three layers are asserted here, because each one catches what the others
cannot:

  the safety gate    refuses the catalogue by name
  the grounding gate refuses anything outside the described schema, including
                     tables nobody has thought of
  the chip filter    stops a model-written option naming a table

A fourth thing is asserted too: the gates must not refuse ordinary work. A
guard that blocks the catalogue and also blocks every WITH query has not made
the product safer, it has made it broken.
"""

from __future__ import annotations

import pytest

from pipeline.followup import clarification_followup
from pipeline.redact import names_a_database_object, safe_clarification
from pipeline.safety import UnsafeSQLError, assert_read_only
from pipeline.sql_semantics import check_against_schema


# ------------------------------------------------- layer 1: the safety gate --

@pytest.mark.parametrize("sql", [
    "SELECT column_name, data_type FROM information_schema.columns",
    "SELECT table_name FROM information_schema.tables",
    "SELECT relname FROM pg_catalog.pg_class",
    "SELECT * FROM pg_class",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT current_database(), pg_size_pretty(1)",
])
def test_the_catalogue_is_refused(sql):
    """A catalogue read is a read, so "read only" never saw a problem here."""
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


@pytest.mark.parametrize("sql", [
    "SELECT task_id FROM tms_task_flat WHERE task_status = 'open'",
    "SELECT t.task_id FROM tms_task_flat t JOIN tms_user_flat u ON u.user_id = t.assigned_user_id",
    "WITH x AS (SELECT task_id FROM tms_task_flat) SELECT COUNT(*) FROM x",
])
def test_ordinary_work_still_runs(sql):
    assert_read_only(sql)


# ---------------------------------------------- layer 2: the grounding gate --

@pytest.mark.parametrize("sql", [
    "SELECT column_name FROM information_schema.columns",
    "SELECT relname FROM pg_catalog.pg_class",
    # The chat history. Revoked at the database too, but that revoke covers
    # two tables and this covers every table that is not described.
    "SELECT question FROM vf_sql_chat_turn",
    "SELECT * FROM some_table_nobody_described",
])
def test_anything_outside_the_described_schema_is_not_grounded(sql):
    assert check_against_schema(sql).grounded is False


@pytest.mark.parametrize("sql", [
    "SELECT task_id FROM tms_task_flat",
    "SELECT t.task_id FROM tms_task_flat t WHERE t.task_status = 'open'",
    "SELECT task_department, COUNT(*) FROM tms_task_flat GROUP BY task_department",
    "SELECT COUNT(*) AS total_count FROM tms_task_flat",
    "SELECT COUNT(*) FROM (SELECT task_id FROM tms_task_flat) s",
])
def test_ordinary_work_is_grounded(sql):
    assert check_against_schema(sql).grounded is True


@pytest.mark.parametrize("sql", [
    "WITH x AS (SELECT task_id FROM tms_task_flat) SELECT COUNT(*) FROM x",
    "WITH a AS (SELECT 1 AS n), b AS (SELECT 2 AS n) SELECT a.n FROM a JOIN b ON b.n = a.n",
])
def test_a_cte_is_not_a_missing_table(sql):
    """The reason this matters is that grounding now decides execution.

    A CTE in a FROM used to be reported as an unknown table. That was only a
    label, so nobody minded. The moment the label became the gate, every
    "WITH" query -- which the prompt explicitly permits -- would have been
    refused.
    """
    check = check_against_schema(sql)
    assert check.grounded is True, sorted(check.unknown_tables)


# ------------------------------------------------- layer 3: the chip filter --

def test_a_model_option_naming_a_table_is_dropped():
    followup = clarification_followup(
        "Which one did you mean?",
        ["tms_user_flat", "tms_user_department_flat"],
    )
    labels = [s.label for s in followup.suggestions]
    assert labels == []
    assert "tms_user_flat" not in str(labels)


def test_readings_written_in_business_words_survive():
    followup = clarification_followup(
        "Which did you mean?", ["Tasks still open", "Tasks already closed"])
    assert [s.label for s in followup.suggestions] == [
        "Tasks still open", "Tasks already closed"]


def test_real_values_are_still_offered():
    """Chips built from the database are data, not identifiers.

    An initiative type like AR_YD_Suiting has the shape of an identifier and
    is exactly what the user needs offered, so the filter must not reach it.
    """
    followup = clarification_followup("Which one?", about="task_sla_status")
    assert set(s.label for s in followup.suggestions) == {"Delayed", "On Time"}


# --------------------------------------------------- the text guard itself --

@pytest.mark.parametrize("text", [
    "tms_user_flat",
    "I searched tms_task_flat",
    "the column is called assigned_user_name",
    "it is a VARCHAR",
    "the data type is integer",
    "column_name and data_type",
])
def test_names_and_types_are_recognised(text):
    assert names_a_database_object(text) is True


@pytest.mark.parametrize("text", [
    "Which department did you mean?",
    "Did you mean the status of the task, or of the initiative?",
    "Delayed",
    "Design Team block",
    "the open tasks for the Sales department this month",
])
def test_business_language_is_not_mistaken_for_a_database_name(text):
    assert names_a_database_object(text) is False


def test_a_clarification_that_lists_columns_is_replaced_not_shown():
    leak = "The columns are user_name VARCHAR and user_id INTEGER"
    assert safe_clarification(leak) != leak
    assert "VARCHAR" not in safe_clarification(leak)


# ------------------------------------------------ the gate, end to end --
#
# The three layers above are unit checks. This is the one that matters: it
# drives a whole turn and asserts the database was never reached.


class _Settings:
    statement_timeout_ms = 5000


class _ScriptedModel:
    def __init__(self, reply):
        self.reply = reply

    def ask(self, question, mcp_config_path, privacy_mode, settings, session=None):
        from pipeline.models import ClaudeRun
        return ClaudeRun(ok=True, result_text=self.reply, duration_ms=1.0,
                         prompt_tokens=10, completion_tokens=10)


def _drive(monkeypatch, reply, question):
    """One turn, with the database replaced by a tripwire."""
    from pipeline import lean_runner
    from pipeline.context import ConversationState
    from pipeline.lean_suite import SuiteTurn
    from pipeline.models import Session

    reached = []

    def _tripwire(settings, sql, timeout_ms=None, readonly_role=True):
        reached.append(sql)
        raise AssertionError("the database was queried: %s" % sql)

    monkeypatch.setattr(lean_runner, "run_readonly", _tripwire)
    monkeypatch.setattr(lean_runner, "get_provider",
                        lambda s: _ScriptedModel(reply))

    turn = SuiteTurn(id="SD01", question=question, expected_sql=None,
                     category="runtime", conversation_id="SD", turn_index=0)
    result = lean_runner.run_turn(
        turn, ConversationState(), [], _Settings(), mcp_config_path=None,
        privacy_mode="strict", session=Session(session_id="sd", turns=[]))
    return result, reached


def test_the_catalogue_query_is_never_executed(monkeypatch):
    """The reported bug, driven end to end.

    The model writes the query it wrote in production. The turn must come back
    without having touched the database, because the rows would have been the
    schema.
    """
    reply = ('{"sql": "SELECT column_name, data_type FROM '
             'information_schema.columns WHERE table_name = 1", '
             '"explanation": "The columns of that table."}')
    result, reached = _drive(monkeypatch, reply, "give me the column names")

    assert reached == [], "the query ran"
    assert not result.actual_result, "rows came back"
    assert result.execution_success is not True


def test_the_user_is_told_something_useful_rather_than_nothing(monkeypatch):
    """A refusal that renders as a blank answer reads as a broken page."""
    from pipeline.redact import safe_error

    reply = ('{"sql": "SELECT column_name FROM information_schema.columns", '
             '"explanation": "here you go"}')
    result, _ = _drive(monkeypatch, reply, "give me the column names")

    shown = safe_error(result.error, getattr(result, "sqlstate", None))
    assert shown, "the turn refused silently"
    # The raw reason names the catalogue; what the user sees must not, and it
    # must point somewhere useful rather than saying "try rephrasing", which
    # cannot help when the question is not about the work at all.
    assert "information_schema" not in shown
    assert "catalogue" not in shown.lower()
    assert "tasks" in shown.lower()


def test_a_query_about_another_table_is_refused_too(monkeypatch):
    """Not a denylist. Anything the schema file does not describe is refused."""
    reply = '{"sql": "SELECT question FROM vf_sql_chat_turn", "explanation": "x"}'
    result, reached = _drive(monkeypatch, reply, "what have people asked?")

    assert reached == []
    assert not result.actual_result
