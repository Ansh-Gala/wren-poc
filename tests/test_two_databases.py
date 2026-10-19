"""Two databases, the request's user, and who may run a question.

No database and no model: connections are faked, and what each one was opened
with is what is checked.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scripts.serve_api as api  # noqa: E402
import database.connection as connection  # noqa: E402
import pipeline.chat_store as chat_store  # noqa: E402
import pipeline.run_access as access  # noqa: E402
from config.settings import Settings, load_settings  # noqa: E402
from pipeline.lean_runner import TurnResult  # noqa: E402
from pipeline.models import QueryResult  # noqa: E402
from pipeline.sql_semantics import check_against_schema  # noqa: E402

TWO = Settings(pg_host="db1", pg_port=5432, pg_database="business", pg_user="owner",
               pg_password="pw-owner", pg_readonly_user="wren_ro", pg_readonly_password="pw-ro",
               history_db_host="db2", history_db_port=6543, history_db_name="chats",
               history_db_user="chat_writer", history_db_password="pw-writer",
               run_roles=("ticket_owner",))


# ------------------------------------------------------ which database --

class Refused(Exception):
    pass


def _record_connects(monkeypatch, module) -> list[dict]:
    opened: list[dict] = []

    def connect(*args, **kwargs):
        opened.append(kwargs)
        raise Refused("no database in tests")

    monkeypatch.setattr(module.psycopg, "connect", connect)
    return opened


def test_business_queries_use_database_one_as_the_read_only_login(monkeypatch):
    opened = _record_connects(monkeypatch, connection)
    connection.close_thread_connection()
    connection.run_readonly(TWO, "SELECT 1")
    assert opened and opened[0]["dbname"] == "business"
    assert opened[0]["host"] == "db1" and opened[0]["user"] == "wren_ro"


def test_chat_writes_use_database_two_as_the_chat_login(monkeypatch):
    opened = _record_connects(monkeypatch, chat_store)
    assert chat_store.ChatStore(TWO, 42).save("s", "q") is None      # swallowed
    assert opened == [{"host": "db2", "port": 6543, "dbname": "chats",
                       "user": "chat_writer", "password": "pw-writer", "connect_timeout": 10}]


class FakeCursor:
    def __init__(self, log):
        self.log, self.result = log, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=()):
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.log.append((text, params))
        self.result = (11,) if text.startswith("INSERT") else None

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, **kwargs):
        return FakeCursor(self.log)


def test_the_request_user_id_is_stored_as_the_chat_owner(monkeypatch):
    log: list = []
    monkeypatch.setattr(chat_store.psycopg, "connect", lambda **k: FakeConnection(log))
    chat_id = chat_store.ChatStore(TWO, 42).save("react-1", "open tasks")
    assert chat_id == 11
    insert = [(q, p) for q, p in log if q.startswith("INSERT")]
    assert '"py_sql_chat" (uid,' in insert[0][0]
    assert insert[0][1][0] == 42


def test_without_a_user_nothing_is_stored():
    assert not chat_store.ChatStore(TWO, None).enabled
    assert not chat_store.ChatStore(TWO, 0).enabled


# ------------------------------------------------- the user, per turn --

def _turn(**fields) -> TurnResult:
    r = TurnResult(turn_id="t.0", conversation_id="t", turn_index=0,
                   category="runtime", question="q")
    for name, value in fields.items():
        setattr(r, name, value)
    return r


@pytest.fixture
def runtime(monkeypatch):
    stores: list[int] = []
    identities: list[int] = []

    class Store:
        enabled = False

        def __init__(self, settings, uid):
            stores.append(uid)

        def load(self, session_id):
            return {"chat_id": None, "turn_index": 0, "history": {"questions": [], "recap": None}}

        def save(self, *a):
            return None

        def record_turn(self, *a):
            pass

    monkeypatch.setattr(api, "ChatStore", Store)
    monkeypatch.setattr(api, "run_turn", lambda turn, *a, **k: _turn(question=turn.question))
    monkeypatch.setattr(api, "resolve_identity",
                        lambda settings, user_id: identities.append(user_id))
    api.SESSIONS.clear()
    rt = api.Runtime.__new__(api.Runtime)
    rt.settings = SimpleNamespace(freshness_tables=(), freshness_message="",
                                  monthly_token_limit=0, run_roles=("ticket_owner",))
    rt.gazetteer, rt.mcp_config_path, rt.privacy = [], None, "strict"
    rt.context_mode, rt.log_path = "state", None
    return rt, stores, identities


def test_a_turn_is_saved_and_answered_for_the_request_user(runtime):
    rt, stores, identities = runtime
    rt.ask({"session_id": "s", "question": "my open tasks"}, 42)
    assert stores == [42] and identities == [42]


def test_two_users_with_one_session_id_share_nothing(runtime):
    rt, _, _ = runtime
    rt.ask({"session_id": "same", "question": "q"}, 1)
    rt.ask({"session_id": "same", "question": "q"}, 2)
    assert api.conversation_for("same", 1) is not api.conversation_for("same", 2)


def test_authorize_checks_the_role_before_the_turn(runtime, monkeypatch):
    rt, stores, _ = runtime
    monkeypatch.setattr(access, "user_roles", lambda s, uid: frozenset({"authenticated", "planner"}))
    with pytest.raises(access.RunNotAllowed):
        rt.authorize({"user_id": 5})
    monkeypatch.setattr(access, "user_roles", lambda s, uid: frozenset({"ticket_owner"}))
    assert rt.authorize({"user_id": "5"}) == 5
    assert stores == [], "authorize runs nothing"


# ------------------------------------------------------- user_id rules --

@pytest.mark.parametrize("value,expected", [(12, 12), ("12", 12), (" 7 ", 7)])
def test_a_user_id_is_a_positive_whole_number(value, expected):
    assert access.user_id_from(value) == expected


@pytest.mark.parametrize("value,code", [
    (None, "user_id_required"), ("", "user_id_required"), ("  ", "user_id_required"),
    (0, "user_id_invalid"), (-1, "user_id_invalid"), ("-1", "user_id_invalid"),
    ("12a", "user_id_invalid"), (1.0, "user_id_invalid"), (True, "user_id_invalid"),
    ([12], "user_id_invalid"), ({"id": 12}, "user_id_invalid"),
])
def test_a_missing_or_malformed_user_id_is_refused(value, code):
    with pytest.raises(access.UserIdError) as raised:
        access.user_id_from(value)
    assert raised.value.code == code


# -------------------------------------------------------- run roles --

def _roles_db(monkeypatch, known=True, roles=("ticket_owner",), error=None):
    access._roles.clear()
    asked: list[str] = []

    def run_readonly(settings, sql):
        asked.append(sql)
        if "tms_user_flat" in sql:
            rows = [[1]] if known else []
        else:
            rows = [[r] for r in roles]
        return QueryResult(columns=[], rows=rows, duration_ms=1.0, error=error)

    monkeypatch.setattr(access, "run_readonly", run_readonly)
    return asked


def test_a_listed_role_may_run(monkeypatch):
    _roles_db(monkeypatch, roles=("planner", "ticket_owner"))
    access.check_run(TWO, 5)


@pytest.mark.parametrize("known,roles,error", [
    (True, ("planner",), None),                 # no listed role
    (False, ("ticket_owner",), None),           # not a TMS user
    (True, ("ticket_owner",), "connection refused"),   # roles unreadable: refuse
])
def test_anything_else_may_not(monkeypatch, known, roles, error):
    _roles_db(monkeypatch, known=known, roles=roles, error=error)
    with pytest.raises(access.RunNotAllowed):
        access.check_run(TWO, 5)


def test_no_run_roles_means_nobody_and_asks_nothing(monkeypatch):
    asked = _roles_db(monkeypatch)
    with pytest.raises(access.RunNotAllowed):
        access.check_run(dataclasses.replace(TWO, run_roles=()), 5)
    assert asked == []


def test_authenticated_means_any_known_user(monkeypatch):
    _roles_db(monkeypatch, roles=())
    access.check_run(dataclasses.replace(TWO, run_roles=("authenticated",)), 5)
    _roles_db(monkeypatch, known=False, roles=())
    with pytest.raises(access.RunNotAllowed):
        access.check_run(dataclasses.replace(TWO, run_roles=("authenticated",)), 5)


def test_the_roles_are_read_from_the_business_database(monkeypatch):
    asked = _roles_db(monkeypatch)
    access.check_run(TWO, 5)
    assert any("vf_user__roles" in sql and "entity_id = 5" in sql for sql in asked)


# ---------------------------------------------------- the view registry --

@pytest.mark.parametrize("table", ["vf_user__roles", "vf_sql_chat", "py_sql_chat", "pg_user"])
def test_a_view_outside_the_registry_is_not_grounded(table):
    assert not check_against_schema(f"SELECT * FROM {table}").grounded


def test_a_registered_view_is_grounded():
    assert check_against_schema("SELECT task_id FROM tms_task_flat").grounded


def test_a_stored_answer_on_an_unlisted_view_is_not_run_again(monkeypatch):
    class Store:
        enabled = True

        def open_chat(self, chat_id):
            return {"chat": {}, "turns": [{"sequence_number": 1, "status": "success",
                                           "generated_sql": "SELECT * FROM vf_user__roles"}]}

    monkeypatch.setattr(connection, "run_readonly",
                        lambda *a: pytest.fail("an unlisted view was queried"))
    status, _ = api.full_csv(TWO, Store(), 1, 1)
    assert status == 422


# ------------------------------------------------------------- settings --

def test_the_two_databases_are_configured_independently(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_HOST=db1\nDATABASE_NAME=business\nDATABASE_USER=owner\n"
        "DATABASE_READONLY_USER=wren_ro\nDATABASE_READONLY_PASSWORD=pw-ro\n"
        "HISTORY_DATABASE_HOST=db2\nHISTORY_DATABASE_PORT=6543\nHISTORY_DATABASE_NAME=chats\n"
        "HISTORY_DATABASE_USER=chat_writer\nHISTORY_DATABASE_PASSWORD=pw-writer\n"
        "CHATBOT_RUN_ROLES= ticket_owner , wcms_admin ,\n", encoding="utf-8")
    s = load_settings(env)
    assert (s.pg_host, s.pg_database, s.pg_readonly_user) == ("db1", "business", "wren_ro")
    assert (s.history_db_host, s.history_db_port, s.history_db_name, s.history_db_user) == \
        ("db2", 6543, "chats", "chat_writer")
    assert s.run_roles == ("ticket_owner", "wcms_admin")
    assert s.problems() == []
    assert "pw-writer" in s.secrets() and "pw-writer" not in repr(s)


def test_the_chat_database_never_falls_back_to_the_business_one(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DATABASE_HOST=db1\nDATABASE_PORT=5433\nDATABASE_NAME=business\n",
                   encoding="utf-8")
    s = load_settings(env)
    assert s.history_db_name == "" and s.history_db_port == 5432
    assert not s.chats_configured


@pytest.mark.parametrize("change,fragment", [
    ({"history_db_host": "db1", "history_db_port": 5432, "history_db_name": "business"},
     "names the business database"),
    ({"history_db_user": "wren_ro"}, "its own login"),
    ({"history_db_user": "owner"}, "its own login"),
    ({"history_db_user": ""}, "need both"),
])
def test_settings_that_would_merge_the_two_are_refused(change, fragment):
    problems = dataclasses.replace(TWO, **change).problems()
    assert any(fragment in p for p in problems)
