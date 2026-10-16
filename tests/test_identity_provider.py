"""The console's user: id from .env, the rest from the database."""

from __future__ import annotations

import pytest

from pipeline import identity_provider
from pipeline.identity import CallerIdentity
from pipeline.identity_provider import resolve_identity
from pipeline.models import QueryResult


def _result(rows, error=None):
    return QueryResult(columns=["value"], rows=rows, duration_ms=1.0, error=error)


@pytest.fixture
def database(monkeypatch):
    """A fake run_readonly that records the SQL it was given."""
    identity_provider._resolved.clear()
    answers = {"user_name": _result([("Asha Rao",)]),
               "department": _result([("Design Team",), ("Sales",)])}
    seen: list[str] = []

    def run_readonly(settings, sql, *args, **kwargs):
        seen.append(sql)
        return answers["user_name" if "user_name" in sql else "department"]

    monkeypatch.setattr(identity_provider, "run_readonly", run_readonly)
    yield answers, seen
    identity_provider._resolved.clear()


@pytest.mark.parametrize("user_id", [0, None, -3])
def test_no_id_is_nobody_and_asks_nothing(database, user_id):
    _, seen = database
    assert resolve_identity(None, user_id) is None
    assert seen == []


def test_the_name_and_every_department_come_from_the_database(database):
    assert resolve_identity(None, 7) == CallerIdentity(7, "Asha Rao", ("Design Team", "Sales"))


def test_the_id_reaches_the_sql_as_a_number(database):
    _, seen = database
    resolve_identity(None, "7")
    assert all("user_id = 7 " in sql for sql in seen)


def test_a_user_the_database_does_not_know_is_nobody(database):
    """A bare id would make the model filter on someone who does not exist."""
    answers, _ = database
    answers["user_name"] = _result([])
    answers["department"] = _result([])
    assert resolve_identity(None, 7) is None


def test_a_failed_lookup_counts_as_no_data(database):
    answers, _ = database
    answers["department"] = _result([], error="boom")
    assert resolve_identity(None, 7) == CallerIdentity(7, "Asha Rao", ())


def test_a_missing_name_is_blank_not_the_word_none(database):
    answers, _ = database
    answers["user_name"] = _result([(None,)])
    assert resolve_identity(None, 7).display_name == ""


def test_a_resolved_user_is_reused_within_the_ttl(database):
    _, seen = database
    resolve_identity(None, 7)
    asked = len(seen)
    resolve_identity(None, 7)
    assert len(seen) == asked, "the second call within the TTL should not query"
