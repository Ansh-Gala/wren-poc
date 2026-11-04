"""PII aliasing through the whole pipeline: what the model is handed, what the
database is handed, and what the chat database keeps between turns.

The model, the database and the detector are all scripted, so the assertions
are on exactly what crossed each boundary. The two that matter:

  the model never sees a value      every prompt, the repair one included
  the database always does          every query: main, early, chart, repair, CSV
"""

from __future__ import annotations

import dataclasses
import json
import sys
import threading
from pathlib import Path

import pytest

from pipeline import chat_store as cs
from pipeline import lean_runner
from pipeline.context import ConversationState
from pipeline.identity import CallerIdentity
from pipeline.lean_suite import SuiteTurn
from pipeline.models import ClaudeRun, QueryResult, Session
from pipeline.pii import PiiError, PiiGuard, PiiVault, stored_aliases
from tests.test_pii import anonymizer

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import scripts.serve_api as api  # noqa: E402

FOUND = {"Rahul Sharma": ("person", 0.99), "Mumbai": ("city", 0.97),
         "rahul@gmail.com": ("email", 0.98), "Amit Rao": ("person", 0.96),
         "Asha Rao": ("person", 0.95), "Neha Joshi": ("person", 0.94)}
VALUES = ("Rahul", "Mumbai", "rahul@", "Amit", "Asha", "Neha")
BRIEF = ("Show me all tasks assigned to Rahul Sharma from Mumbai and check "
         "his email rahul@gmail.com")
BY_RAHUL = "SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'PERSON_001'"


def reply(sql: str | None = None, **fields) -> str:
    body = {"sql": sql, "explanation": "Tasks for PERSON_001."} if sql else {}
    return json.dumps({**body, **fields})


class _Settings:
    statement_timeout_ms = 5000


class World:
    """A scripted model and database, recording what each was handed."""

    def __init__(self) -> None:
        self.replies: list[str] = []
        self.prompts: list[str] = []
        self.executed: list[str] = []
        self.db_errors: list[str] = []

    def ask(self, question, mcp_config_path, privacy_mode, settings, session=None, **_):
        context = getattr(session, "context_block", "") or ""
        self.prompts.append(context + "\n" + question)
        text = self.replies.pop(0) if self.replies else reply(BY_RAHUL)
        return ClaudeRun(ok=True, result_text=text, duration_ms=0.0)

    def run_readonly(self, settings, sql, timeout_ms=None):
        self.executed.append(sql)
        if self.db_errors:
            return QueryResult(columns=[], rows=[], duration_ms=0.0,
                               error=self.db_errors.pop(0), sqlstate="22P02")
        return QueryResult(columns=["task_id"], rows=[(1,), (2,)], duration_ms=0.0)

    def leaked(self) -> list[str]:
        return [p for p in self.prompts if any(v in p for v in VALUES)]


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(lean_runner, "get_provider", lambda settings: w)
    monkeypatch.setattr(lean_runner, "run_readonly", w.run_readonly)
    return w


@pytest.fixture
def thread(world):
    """Turns of one conversation, run_turn as the suites call it."""
    guard = PiiGuard(anonymizer(FOUND), PiiVault())
    state = ConversationState()
    session = Session(session_id="p", turns=[], context_block="")
    count = [0]

    def ask(question, *replies, identity=None, aliasing=True):
        world.replies.extend(replies)
        turn = SuiteTurn(id=f"p.{count[0]}", question=question, expected_sql=None,
                         category="runtime", conversation_id="p", turn_index=count[0])
        count[0] += 1
        return lean_runner.run_turn(turn, state, _Settings(), None, "strict", session,
                                    identity=identity, pii=guard if aliasing else None)

    ask.guard, ask.state = guard, state
    return ask


# ------------------------------------------------------------- run_turn --

def test_the_model_never_sees_a_value_and_the_database_always_does(world, thread):
    r = thread(BRIEF, reply(BY_RAHUL))

    assert world.leaked() == []
    assert ("tasks assigned to PERSON_001 from LOCATION_001 and check his email EMAIL_001"
            in world.prompts[0])
    assert "PLACEHOLDERS" in world.prompts[0]
    assert world.executed == [
        "SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'Rahul Sharma'"]
    # What the turn keeps is the model's SQL, never the restored one.
    assert r.generated_sql == BY_RAHUL
    assert r.question == BRIEF
    assert [a["alias"] for a in r.pii_new_aliases] == ["PERSON_001", "LOCATION_001", "EMAIL_001"]
    assert lean_runner.logged(r)["pii_new_aliases"] == ["PERSON_001", "LOCATION_001", "EMAIL_001"]


def test_a_follow_up_keeps_the_alias_and_the_state_holds_aliases_only(world, thread):
    thread(BRIEF, reply(BY_RAHUL))
    thread("only Rahul Sharma's closed ones, and Amit Rao's",
           reply(BY_RAHUL + " AND task_status = 'closed'"))

    assert world.leaked() == []
    assert "only PERSON_001's closed ones, and PERSON_002's" in world.prompts[1]
    # The first question reaches turn two in its alias form.
    assert "tasks assigned to PERSON_001 from LOCATION_001" in world.prompts[1]
    assert all("Rahul" not in q for q in thread.state.recent_questions)
    assert "PERSON_001" in json.dumps(thread.state.active_filters)
    assert [e["alias"] for e in thread.guard.vault.entries()] == [
        "PERSON_001", "LOCATION_001", "EMAIL_001", "PERSON_002"]


def test_a_database_error_quoting_a_value_is_masked_before_the_repair(world, thread):
    world.db_errors.append('invalid input syntax for type integer: "Rahul Sharma"')
    r = thread("tasks of Rahul Sharma",
               reply("SELECT task_id FROM tms_task_flat WHERE assigned_user_id = 'PERSON_001'"),
               reply(BY_RAHUL))

    assert r.repair_attempted and r.repair_succeeded
    assert world.leaked() == []
    assert 'integer: "PERSON_001"' in world.prompts[1]
    assert r.pii_masked == 1
    assert world.executed[1] == ("SELECT task_id FROM tms_task_flat "
                                 "WHERE assigned_user_name = 'Rahul Sharma'")


def test_an_invented_alias_is_refused_and_repaired_never_run(world, thread):
    r = thread("tasks of Rahul Sharma",
               reply("SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'PERSON_009'"),
               reply(BY_RAHUL))

    # The refused statement never reached the database.
    assert world.executed == [
        "SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'Rahul Sharma'"]
    assert "PERSON_009 is not one of the placeholders" in world.prompts[1]
    assert r.repair_succeeded and r.execution_success


def test_an_alias_written_as_a_bare_word_never_reaches_the_database(world, thread):
    r = thread("tasks of Rahul Sharma",
               reply("SELECT task_id FROM tms_task_flat WHERE assigned_user_name = PERSON_001"),
               reply("SELECT task_id FROM tms_task_flat WHERE assigned_user_name = PERSON_001 "
                     "AND 1 = 1"))
    assert not any("PERSON_001" in sql for sql in world.executed)
    assert not r.execution_success


def test_the_signed_in_users_name_reaches_the_model_as_an_alias(world, thread):
    thread("my open tasks", reply("SELECT task_id FROM tms_task_flat WHERE assigned_user_id = 7"),
           identity=CallerIdentity(7, "Asha Rao", ("Sales",)))
    assert world.leaked() == []
    assert "name: PERSON_001" in world.prompts[0]
    # Departments are business units the rules filter on as written.
    assert "departments: Sales" in world.prompts[0]
    assert "  id: 7" in world.prompts[0]


def test_the_chart_query_gets_its_values_too(world, thread):
    chart = {"type": "pie", "category": "task_status", "values": ["n"],
             "sql": "SELECT task_status, COUNT(*) AS n FROM tms_task_flat "
                    "WHERE assigned_user_name = 'PERSON_001' GROUP BY task_status"}
    r = thread("chart of Rahul Sharma's tasks by status", reply(BY_RAHUL, chart=chart))
    assert r.chart_error is None
    assert world.executed[-1] == ("SELECT task_status, COUNT(*) AS n FROM tms_task_flat "
                                  "WHERE assigned_user_name = 'Rahul Sharma' GROUP BY task_status")


def test_the_early_streamed_query_gets_its_values_too(world, thread):
    thread.guard.vault.alias_for("person", "Rahul Sharma")
    memo, events = {}, []
    lean_runner._execute_early(_Settings(), reply(BY_RAHUL), memo, events.append, thread.guard)
    assert world.executed == [
        "SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'Rahul Sharma'"]
    # Memoised and reported under the model's SQL, never the real one.
    assert list(memo) == [BY_RAHUL]
    assert events[0]["generated_sql"] == BY_RAHUL


def test_an_alias_is_not_mistaken_for_a_column_name():
    # PERSON_001 has snake_case's shape, which is the identifier guard's tell.
    # Left to it, every sentence carrying an alias was dropped: explanations,
    # clarifications, options and -- worst -- the recap, so the thread forgot.
    from pipeline.context import accept_recap
    from pipeline.redact import names_a_database_object

    assert not names_a_database_object("Open tasks for PERSON_001 in LOCATION_002.")
    assert accept_recap("Looking at PERSON_001's open tasks.") == \
        "Looking at PERSON_001's open tasks."
    # Real tells still trip it.
    assert names_a_database_object("Tasks of PERSON_001 from tms_task_flat")
    assert names_a_database_object("the WF_001 workflow")


def test_a_recap_and_a_clarification_carrying_aliases_are_kept(world, thread):
    thread("tasks of Rahul Sharma", reply(BY_RAHUL, recap="Looking at PERSON_001's tasks."))
    assert thread.state.rolling_recap == "Looking at PERSON_001's tasks."

    r = thread("and Amit Rao?", json.dumps({
        "clarify": "Do you want PERSON_002's tasks alone, or beside PERSON_001's?",
        "options": ["PERSON_002 alone", "PERSON_002 and PERSON_001 together"]}))
    assert r.clarification.startswith("Do you want PERSON_002's tasks alone")
    assert [s["label"] for s in r.followup["suggestions"]] == [
        "PERSON_002 alone", "PERSON_002 and PERSON_001 together"]
    assert world.leaked() == []


def test_aliasing_off_changes_nothing(world, thread):
    r = thread(BRIEF, reply("SELECT task_id FROM tms_task_flat "
                            "WHERE assigned_user_name = 'Rahul Sharma'"), aliasing=False)
    assert "Rahul Sharma" in world.prompts[0]
    assert "PLACEHOLDERS" not in world.prompts[0]
    assert not r.pii_active and r.pii_new_aliases == []


def test_conversations_running_at_once_keep_their_own_aliases(world):
    shared = anonymizer(FOUND)
    results: dict[str, str] = {}

    def converse(name: str, person: str) -> None:
        vault = PiiVault()
        PiiGuard(shared, vault).anonymize(f"tasks of {person}")
        results[name] = PiiGuard(shared, vault).restore_sql(BY_RAHUL)

    threads = [threading.Thread(target=converse, args=(f"c{i}", p))
               for i, p in enumerate(["Rahul Sharma", "Amit Rao", "Neha Joshi"] * 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for name, sql in results.items():
        person = ["Rahul Sharma", "Amit Rao", "Neha Joshi"][int(name[1:]) % 3]
        assert sql.endswith(f"'{person}'")


# ------------------------------------------------------------ chat store --

def _turn_result(**fields) -> lean_runner.TurnResult:
    r = lean_runner.TurnResult(turn_id="t.0", conversation_id="t", turn_index=0,
                               category="runtime", question="q")
    for name, value in fields.items():
        setattr(r, name, value)
    return r


def test_a_turn_stores_the_aliases_it_introduced():
    entries = [{"alias": "PERSON_001", "label": "person", "original": "Rahul Sharma"}]
    meta = json.loads(cs.metadata_for(_turn_result(pii_active=True, pii_new_aliases=entries,
                                                   pii_masked=2), "q"))
    assert meta["pii"] == {"new_aliases": entries, "masked": 2}
    # Off, nothing is written -- and nothing marks the turn as screened.
    assert "pii" not in json.loads(cs.metadata_for(_turn_result(), "q"))
    # On with nothing found, the empty list still marks the turn screened.
    assert json.loads(cs.metadata_for(_turn_result(pii_active=True), "q"))["pii"] == \
        {"new_aliases": [], "masked": 0}


def test_the_aliases_survive_when_the_metadata_is_cut_to_fit():
    entries = [{"alias": "PERSON_001", "label": "person", "original": "Rahul Sharma"}]
    state = ConversationState()
    state.recent_questions = ["x" * 160] * 10
    state.rolling_recap = "y" * 40000
    meta = json.loads(cs.metadata_for(
        _turn_result(pii_active=True, pii_new_aliases=entries, raw_output="z" * 50000),
        "q", state))
    assert "state" not in meta and "raw_output" not in meta
    assert meta["pii"]["new_aliases"] == entries


class _Cursor:
    def __init__(self, rows):
        self.rows, self.sql = rows, None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


def _store() -> cs.ChatStore:
    settings = dataclasses.replace(api.load_settings(), history_db_name="chats",
                                   history_db_user="writer", save_chats=True)
    return cs.ChatStore(settings, 5)


def test_history_says_which_turns_ran_with_aliasing():
    # Newest first, as the query returns them.
    rows = [("tasks of PERSON_001", None, 1, "About PERSON_001.", 1),
            ("tasks of Neha Joshi", None, 1, "About Neha Joshi.", 0)]
    history = _store()._history(_Cursor(rows), 1)
    assert history == {"questions": ["tasks of Neha Joshi", "tasks of PERSON_001"],
                       "screened": [False, True], "recap": "About PERSON_001.",
                       "recap_screened": True}


def test_every_turns_aliases_are_read_oldest_first():
    rows = [([{"alias": "PERSON_001", "label": "person", "original": "A"}],), (None,),
            ('[{"alias": "PERSON_002", "label": "person", "original": "B"}]',)]
    assert [a["alias"] for a in _store()._aliases(_Cursor(rows), 1)] == ["PERSON_001", "PERSON_002"]


def test_a_chat_that_could_not_be_loaded_says_so(monkeypatch):
    store = _store()
    monkeypatch.setattr(store, "_connect", lambda: (_ for _ in ()).throw(OSError("down")))
    assert store.load("s")["ok"] is False


# ------------------------------------------------- the server, end to end --

class FakeStore:
    """The chat database, as rows in memory, written by the real metadata_for."""

    rows: list[dict] = []
    fail_load = False
    fail_record = False

    def __init__(self, settings, uid) -> None:
        self.uid = uid

    enabled = True

    def load(self, session_id) -> dict:
        empty = {"questions": [], "screened": [], "recap": None, "recap_screened": True}
        if FakeStore.fail_load:
            return {"chat_id": None, "turn_index": 0, "ok": False, "aliases": [], "history": empty}
        if not FakeStore.rows:
            return {"chat_id": None, "turn_index": 0, "ok": True, "aliases": [], "history": empty}
        metas = [json.loads(row["metadata"]) for row in FakeStore.rows]
        recent = list(zip(FakeStore.rows, metas))[-10:]
        recap = [m for m in metas if "state" in m]
        return {"chat_id": 1, "turn_index": len(FakeStore.rows), "ok": True,
                "aliases": stored_aliases(metas),
                "history": {"questions": [m["pipeline"]["normalized_question"] or row["question"]
                                          for row, m in recent],
                            "screened": ["pii" in m for _, m in recent],
                            "recap": recap[-1]["state"]["rolling_recap"] if recap else None,
                            "recap_screened": "pii" in recap[-1] if recap else True}}

    def save(self, session_id, question="") -> int:
        return 1

    def record_turn(self, chat_id, turn_index, question, r, full, state=None) -> bool:
        if FakeStore.fail_record:
            return False
        FakeStore.rows.append({"question": question, "generated_sql": r.generated_sql,
                               "status": cs.turn_status(r), "sequence_number": turn_index + 1,
                               "metadata": cs.metadata_for(r, question, state)})
        return True


@pytest.fixture
def server(monkeypatch, world):
    FakeStore.rows, FakeStore.fail_load, FakeStore.fail_record = [], False, False
    monkeypatch.setattr(api, "ChatStore", FakeStore)
    monkeypatch.setattr(api, "SESSIONS", {})
    monkeypatch.setattr(api, "resolve_identity", lambda settings, user_id: None)
    runtime = object.__new__(api.Runtime)
    runtime.settings = dataclasses.replace(api.load_settings(), pii_aliasing=True,
                                           monthly_token_limit=0)
    runtime.anonymizer = anonymizer(FOUND)
    runtime.mcp_config_path, runtime.privacy, runtime.context_mode = None, "strict", "state"
    runtime.log_path, runtime.log_lock = None, threading.Lock()

    def ask(question, *replies):
        world.replies.extend(replies)
        return runtime.ask({"question": question, "session_id": "s1", "debug": True}, 5)

    ask.runtime = runtime
    return ask


def test_the_reader_sees_values_and_the_chat_stores_aliases(world, server):
    full = server("tasks of Rahul Sharma", reply(BY_RAHUL, next=["What about PERSON_001's "
                                                                 "closed ones?", "And by status?"]))
    assert full["explanation"] == "Tasks for Rahul Sharma."
    assert full["followup"]["suggestions"][0]["label"] == "What about Rahul Sharma's closed ones?"
    assert full["generated_sql"] == BY_RAHUL
    meta = json.loads(FakeStore.rows[0]["metadata"])
    assert meta["pii"]["new_aliases"] == [
        {"alias": "PERSON_001", "label": "person", "original": "Rahul Sharma"}]
    assert meta["pipeline"]["normalized_question"] == "tasks of PERSON_001"
    assert FakeStore.rows[0]["generated_sql"] == BY_RAHUL


def test_debug_shows_how_the_turn_was_aliased_and_public_answers_never_do(world, server):
    from pipeline.redact import public_response

    full = server("tasks of Rahul Sharma", reply(BY_RAHUL))
    pii = full["pii"]
    assert pii["enabled"] and pii["model"] == server.runtime.settings.pii_model
    assert pii["sent_to_llm"] == "tasks of PERSON_001"
    assert pii["aliases"] == [{"alias": "PERSON_001", "label": "person",
                               "original": "Rahul Sharma", "new": True, "used": True}]
    assert pii["generated_sql"] == BY_RAHUL
    assert pii["executed_sql"].endswith("= 'Rahul Sharma'")
    assert "WHERE\n  assigned_user_name = 'Rahul Sharma'" in pii["executed_sql_pretty"]
    assert full["generated_sql_pretty"].startswith("SELECT\n  task_id\nFROM tms_task_flat")
    # Debug off: the mapping and the SQL never leave the server.
    public = public_response(full)
    assert "pii" not in public and "generated_sql_pretty" not in public
    assert "PERSON_001" not in json.dumps(public)


def test_aliasing_off_is_reported_as_off(world, server):
    server.runtime.anonymizer = None
    assert server("tasks of Rahul Sharma", reply(BY_RAHUL))["pii"] == {"enabled": False}


def test_the_console_is_told_the_model_and_the_modes(server):
    from fastapi.testclient import TestClient

    api.app.state.runtime = server.runtime
    info = TestClient(api.app).get("/info").json()
    assert info["llm"]["mode"] in ("cli", "api") and "model" in info["llm"]
    assert info["pii"] == {"enabled": True, "model": server.runtime.settings.pii_model}


def test_after_a_restart_a_new_person_gets_the_next_number_never_001_again(world, server,
                                                                          monkeypatch):
    server("tasks of Rahul Sharma", reply(BY_RAHUL))
    # A restart: the in-memory conversation is gone; only the chat database is left.
    monkeypatch.setattr(api, "SESSIONS", {})
    server("now Amit Rao's", reply("SELECT task_id FROM tms_task_flat "
                                   "WHERE assigned_user_name = 'PERSON_002'"))

    assert world.leaked() == []
    assert "now PERSON_002's" in world.prompts[1]
    assert "tasks of PERSON_001" in world.prompts[1]          # history, rebuilt
    assert world.executed[1].endswith("= 'Amit Rao'")
    assert json.loads(FakeStore.rows[1]["metadata"])["pii"]["new_aliases"] == [
        {"alias": "PERSON_002", "label": "person", "original": "Amit Rao"}]


def test_with_saving_paused_the_chat_keeps_its_aliases_and_its_thread(world, server,
                                                                     monkeypatch):
    # SAVE_CHATS=false: nothing is loaded or recorded.
    monkeypatch.setattr(FakeStore, "enabled", False)
    FakeStore.fail_record = True
    server("tasks of Rahul Sharma", reply(BY_RAHUL))
    server("now Amit Rao's", reply("SELECT task_id FROM tms_task_flat "
                                   "WHERE assigned_user_name = 'PERSON_002'"))

    assert FakeStore.rows == []
    assert world.leaked() == []
    assert "now PERSON_002's" in world.prompts[1]
    assert "tasks of PERSON_001" in world.prompts[1]          # the thread was not reset
    assert world.executed[1].endswith("= 'Amit Rao'")


def test_a_turn_saved_before_aliasing_was_on_is_anonymized_on_the_way_in(world, server):
    old = _turn_result(normalized_question="tasks of Neha Joshi")
    FakeStore.rows.append({"question": "tasks of Neha Joshi", "generated_sql": None,
                           "status": "success", "sequence_number": 1,
                           "metadata": cs.metadata_for(old, "tasks of Neha Joshi",
                                                       ConversationState())})
    server("and the closed ones", reply("SELECT task_id FROM tms_task_flat "
                                        "WHERE assigned_user_name = 'PERSON_001'"))
    assert world.leaked() == []
    assert "tasks of PERSON_001" in world.prompts[0]
    assert world.executed[0].endswith("= 'Neha Joshi'")


def test_a_chat_whose_aliases_cannot_be_read_is_not_answered(world, server):
    FakeStore.fail_load = True
    with pytest.raises(PiiError):
        server("tasks of Rahul Sharma", reply(BY_RAHUL))
    assert world.prompts == [] and world.executed == []


def test_an_unsaved_turn_leaves_no_alias_behind_in_memory(world, server):
    FakeStore.fail_record = True
    server("tasks of Rahul Sharma", reply(BY_RAHUL))
    conversation = api.SESSIONS[(5, "s1")]
    assert conversation.state.recent_questions == []
    assert conversation.state.active_filters == {}


def test_a_reopened_chat_reads_with_its_values(world, server):
    server("tasks of Rahul Sharma", reply(BY_RAHUL))
    row = {**FakeStore.rows[0], "llm_response": "Tasks for PERSON_001.", "response_type":
           "sql_result", "created_at": 0}
    shown = api.present_chat({"chat": {"id": 1, "session_id": "s1", "title": "t",
                                       "created_at": 0, "updated_at": 0}, "turns": [row]},
                             debug=False)
    assert shown["turns"][0]["explanation"] == "Tasks for Rahul Sharma."


def test_the_csv_download_reruns_the_query_with_its_values(world, server, monkeypatch):
    server("tasks of Rahul Sharma", reply(BY_RAHUL))
    ran = []
    monkeypatch.setattr("database.connection.run_readonly",
                        lambda settings, sql, *a: ran.append(sql) or
                        QueryResult(columns=["task_id"], rows=[(1,)], duration_ms=0.0))

    class Opened:
        enabled = True

        def open_chat(self, chat_id):
            return {"chat": {"id": 1}, "turns": FakeStore.rows}

    status, body = api.full_csv(server.runtime.settings, Opened(), 1, 1)
    assert status == 200
    assert ran == ["SELECT task_id FROM tms_task_flat WHERE assigned_user_name = 'Rahul Sharma'"]
