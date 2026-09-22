"""Conversations, and the two ways one goes wrong.

The layers under `pipeline/` are compared against the PHP port turn by turn by
tests/parity/check.php in the Drupal module, and they agree on every one. What
that harness does not cover is `lean_runner` itself -- the order the steps run
in, and the branches that decide whether a turn is a follow-up, a fresh
question or an answer to something the system asked. That is exactly where a
conversation is lost.

Two failures are hunted here, and they are opposites:

  LEAKAGE  a constraint from earlier survives into a turn that should not have
           it, so an answer comes back quietly narrower than the question.
  LOSS     something the user established is dropped, so a follow-up is
           answered as though the thread had not happened.

Neither is visible in the answer -- a leaked filter produces a perfectly
plausible table -- so the assertions are on what the model was actually handed,
not on whether a query came back.

The model is scripted. Every layer under test is deterministic, and a real one
would make the results unrepeatable while testing nothing extra. What the
script controls is the SQL, because the state is folded from the SQL that ran:
that is how a case reproduces a model which forgets a filter or answers
something adjacent to the question.
"""

from __future__ import annotations

import json

import pytest

from pipeline import lean_runner
from pipeline.context import ConversationState, render_context
from pipeline.lean_suite import SuiteTurn
from pipeline.models import ClaudeRun, QueryResult, Session

OPEN_SALES = (
    "SELECT task_id, task_display_name FROM tms_task_flat "
    "WHERE task_status = 'open' AND task_department = 'Sales'"
)
OPEN_SALES_DELAYED = (
    "SELECT task_id FROM tms_task_flat WHERE task_status = 'open' "
    "AND task_department = 'Sales' AND task_sla_status = 'Delayed'"
)
ONE_INITIATIVE = (
    "SELECT business_object_id FROM tms_initiative_flat "
    "WHERE business_object_id = '123'"
)
ALL_USERS = "SELECT user_id, user_full_name FROM tms_user_flat"


def sql(statement: str, goal: str | None = None) -> str:
    reply: dict = {"sql": statement, "explanation": "Here is what you asked for."}
    if goal:
        reply["goal"] = goal
    return json.dumps(reply)


def clarify(question: str, options: list[str] | None = None) -> str:
    reply: dict = {"clarify": question}
    if options:
        reply["options"] = options
    return json.dumps(reply)


class _Settings:
    """Only the one field the executing half reads."""

    statement_timeout_ms = 5000


class Recorder:
    """A model that answers from a script and remembers what it was told."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.seen: list[dict] = []

    def ask(self, question, mcp_config_path, privacy_mode, settings, session):
        context = getattr(session, "context_block", "") or ""
        self.seen.append({"question": question, "context": context})
        reply = self.replies.pop(0) if self.replies else '{"sql": "SELECT 1"}'
        return ClaudeRun(ok=True, result_text=reply, duration_ms=0.0)


@pytest.fixture
def converse(monkeypatch, tmp_path):
    """Run a scripted thread, returning the results and what the model saw."""

    def run(script: list[tuple[str, str]]):
        recorder = Recorder([reply for _, reply in script])
        monkeypatch.setattr(lean_runner, "get_provider", lambda settings: recorder)
        # No database. Every case here is about what reaches the model, and the
        # rows only decide whether a follow-up is offered at all -- so one row
        # is enough and a real connection would only make the test need one.
        monkeypatch.setattr(lean_runner, "run_readonly",
                            lambda *a, **k: QueryResult(
                                columns=["n"], rows=[(1,)], duration_ms=0.0))

        state = ConversationState()
        session = Session(session_id="t", turns=[], context_block="", lean=True)
        results = []
        for index, (question, _) in enumerate(script):
            turn = SuiteTurn(id=f"t.{index}", question=question,
                             expected_sql=None, category="runtime",
                             conversation_id="t", turn_index=index)
            results.append(lean_runner.run_turn(
                turn, state, [], settings=_Settings(), mcp_config_path=tmp_path,
                privacy_mode="strict", session=session,
            ))
        return results, state, recorder

    return run


def shown(recorder, index: int) -> str:
    return recorder.seen[index]["context"]


# ------------------------------------------------------------- follow-ups --

def test_a_narrowing_follow_up_keeps_what_it_did_not_mention(converse):
    results, state, recorder = converse([
        ("show me open tasks for Sales", sql(OPEN_SALES)),
        ("only the delayed ones", sql(OPEN_SALES_DELAYED)),
    ])
    assert results[1].decision == "follow_up"
    # The user restated nothing, so everything has to come from the thread.
    assert "Sales" in shown(recorder, 1)
    assert state.active_goal == "show me open tasks for Sales"


def test_the_goal_survives_a_run_of_follow_ups(converse):
    _, state, _ = converse([
        ("show me open tasks for Sales", sql(OPEN_SALES)),
        ("only the delayed ones", sql(OPEN_SALES_DELAYED)),
        ("sort by due date", sql(OPEN_SALES_DELAYED + " ORDER BY task_due_date")),
        ("just the top 5", sql(OPEN_SALES_DELAYED + " LIMIT 5")),
    ])
    assert state.active_goal == "show me open tasks for Sales"


def test_a_restated_goal_replaces_one_the_user_has_moved_past(converse):
    # "forget the department" leaves a goal still naming Sales beside filters
    # that no longer do. Only the model can see the aim moved.
    _, state, _ = converse([
        ("open tasks for Sales", sql(OPEN_SALES)),
        ("forget the department, all of them",
         sql("SELECT task_id FROM tms_task_flat WHERE task_status = 'open'",
             goal="show me open tasks")),
    ])
    assert state.active_goal == "show me open tasks"
    # The department is no longer stated as a filter in force -- that section
    # is gone from the block entirely. It survives only as something the user
    # once asked, which is what lets "no, I meant all of them" be understood
    # at all. Saying it has been dropped is the recap's job.
    assert "filters in force" not in render_context(state)
    assert "task_department" not in render_context(state)


def test_a_wandering_model_cannot_rewrite_the_users_aim(converse):
    _, state, _ = converse([
        ("open tasks for Sales", sql(OPEN_SALES)),
        ("only the delayed ones", sql(ALL_USERS)),
    ])
    assert state.active_goal == "open tasks for Sales"


# ---------------------------------------------------------------- subject --

def test_the_subject_survives_a_query_that_omits_it(converse):
    _, state, recorder = converse([
        ("show me initiative 123", sql(ONE_INITIATIVE)),
        # The model drops the id entirely. The thread must not.
        ("what tasks are in it", sql("SELECT task_id FROM tms_task_flat")),
    ])
    # Still tracked -- the suggestion chips are built from it -- and no longer
    # rendered into the prompt.
    assert state.active_subject["label"] == "initiative 123"
    assert "still about" not in render_context(state)


def test_one_record_keeps_one_name_across_its_synonyms(converse):
    # tms_task_flat calls it bo_id and tms_initiative_flat business_object_id.
    # Renaming it mid-thread would read as a change of subject.
    _, state, _ = converse([
        ("show me initiative 123", sql(ONE_INITIATIVE)),
        ("who owns it",
         sql("SELECT assigned_user_name FROM tms_task_flat WHERE bo_id = '123'")),
    ])
    assert state.active_subject["label"] == "initiative 123"
    assert state.active_goal == "show me initiative 123"


def test_the_same_number_on_another_thing_is_a_change_of_subject(converse):
    _, state, _ = converse([
        ("show me initiative 123", sql(ONE_INITIATIVE)),
        ("no i meant task 123",
         sql("SELECT task_id FROM tms_task_flat WHERE task_id = '123'")),
    ])
    assert state.active_subject["label"] == "task 123"
    assert state.active_goal == "no i meant task 123"


def test_a_list_does_not_pin_the_thread_to_a_row(converse):
    _, state, _ = converse([
        ("show me tasks 1, 2 and 3",
         sql("SELECT task_id FROM tms_task_flat WHERE task_id IN ('1','2','3')")),
    ])
    assert state.active_subject is None


# ---------------------------------------------------------- clarification --

def test_a_numbered_answer_resumes_the_original_question(converse):
    results, _, recorder = converse([
        ("which departments are performing poorly?",
         clarify("Which measure?", ["Most open tasks", "Most delayed tasks", "Most issues"])),
        ("2", sql(OPEN_SALES)),
    ])
    assert results[1].decision == "clarification_response"
    assert recorder.seen[1]["question"] == (
        "which departments are performing poorly? (Most delayed tasks)")
    assert results[1].resumed_answering == "Which measure?"


def test_an_unreadable_reply_keeps_the_question_and_its_options_in_view(converse):
    # The failure this closes: the reply reached the model as a bare token and
    # it answered that it had no idea what the conversation was about.
    results, _, recorder = converse([
        ("which departments are performing poorly?",
         clarify("Which measure?", ["Most open tasks", "Most delayed tasks"])),
        ("hmm dunno", sql(OPEN_SALES)),
    ])
    assert results[1].decision == "clarification_response"
    context = shown(recorder, 1)
    assert "Which measure?" in context
    assert "(2) Most delayed tasks" in context


def test_the_carry_forward_clears_itself_and_cannot_wedge(converse):
    _, state, _ = converse([
        ("which departments are performing poorly?",
         clarify("Which measure?", ["Most open tasks", "Most delayed tasks"])),
        ("hmm dunno", clarify("Still not sure what you mean.")),
        ("how many tasks are there?", sql("SELECT COUNT(*) FROM tms_task_flat")),
    ])
    assert state.awaiting_answer_to is None


def test_ignoring_the_question_and_asking_something_else_is_allowed(converse):
    _, _, recorder = converse([
        ("which departments are performing poorly?",
         clarify("Which measure?", ["Most open tasks", "Most delayed tasks"])),
        ("actually show me every user in the system", sql(ALL_USERS)),
    ])
    assert recorder.seen[1]["question"] == "actually show me every user in the system"


# ----------------------------------------------------------------- leakage --

def test_a_pinned_subject_is_no_longer_asserted_as_still_in_force(converse):
    """The guarantee moved, deliberately, and this records where it went.

    It used to be absolute: the subject was withheld, so it could not be
    re-applied. Now the user's own questions travel, so "show me initiative
    123" is visible on the next turn whatever that turn is about.

    What must not happen is this module telling the model the subject is still
    in force. A remembered question is history; "still about: initiative 123"
    was an instruction. The first is for the model to weigh, the second it had
    to obey.

    Whether the model then weighs it correctly is a question about the model,
    and the benchmark answers it -- these are the conversational turns in the
    lean suite.
    """
    _, _, recorder = converse([
        ("show me initiative 123", sql(ONE_INITIATIVE)),
        ("how many users are there in total?",
         sql("SELECT COUNT(*) FROM tms_user_flat")),
    ])
    block = shown(recorder, 1)
    assert "still about" not in block
    assert "filters in force" not in block
    # The history is there, as history.
    assert "show me initiative 123" in block


def test_a_wh_question_with_a_main_verb_is_not_a_fragment(converse):
    # "which roles BELONG to sales" carries no auxiliary, so it used to read as
    # a fragment and inherit the previous question's filters.
    _, _, recorder = converse([
        ("open tasks for Sales", sql(OPEN_SALES)),
        ("which roles belong to the sales department?",
         sql("SELECT role_name FROM tms_role_flat")),
    ])
    assert "task_department = 'Sales'" not in shown(recorder, 1)


def test_a_table_the_noun_list_forgot_is_not_a_fragment(converse):
    _, _, recorder = converse([
        ("open tasks for Sales", sql(OPEN_SALES)),
        ("what attachments do we have?",
         sql("SELECT attachment_id FROM tms_attachment_flat")),
    ])
    assert "task_department = 'Sales'" not in shown(recorder, 1)


def test_widening_wh_does_not_swallow_a_genuine_follow_up(converse):
    # "ones" is not a subject noun, so the noun gate still holds this as a
    # follow-up -- which is what stops the looser wh-opener turning every
    # narrowing into a fresh question.
    results, _, recorder = converse([
        ("open tasks for Sales", sql(OPEN_SALES)),
        ("which ones are delayed?", sql(OPEN_SALES_DELAYED)),
    ])
    assert results[1].decision == "follow_up"
    assert "Sales" in shown(recorder, 1)


def test_an_explicit_reset_drops_the_subject_before_the_model_sees_it(converse):
    _, state, recorder = converse([
        ("show me initiative 123", sql(ONE_INITIATIVE)),
        ("start over. how many tasks are there?",
         sql("SELECT COUNT(*) FROM tms_task_flat")),
    ])
    assert shown(recorder, 1) == ""
    assert state.active_subject is None
