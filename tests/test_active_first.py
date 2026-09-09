"""The active-first default: what the model is told when no status is named.

Active-first is a business rule rather than a SQL rewrite, so what can be
asserted here is that the rule reaches the model intact and leaks into none of
the layers that must stay unaware of it. Whether the model then complies is an
accuracy question, and accuracy is measured by
benchmark/active_first_questions.yaml -- not asserted in a unit test.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _rule(name: str) -> dict:
    doc = yaml.safe_load(
        (ROOT / "metadata" / "business_rules.yaml").read_text(encoding="utf-8"))
    found = [r for r in doc["rules"] if r["name"] == name]
    assert len(found) == 1, f"expected exactly one {name!r} rule, found {len(found)}"
    return found[0]


def test_the_default_names_both_status_columns_that_exist():
    """Both, and only both.

    tms_user_flat has no status column, so a rule naming one would be telling
    the model to filter on something that is not there.
    """
    rule = _rule("default_to_active")
    text = rule["definition"] + rule["scope"]
    assert "business_object_status = 'Active'" in text
    assert "task_status = 'open'" in text
    assert "user_status" not in text


def test_the_default_carves_out_the_questions_it_must_not_touch():
    """The carve-outs are the rule. Without them it is simply wrong.

    Each phrase below stands for a question class that must still see every
    row: a stated status, an explicit request for every status, a distribution
    across statuses, a count of distinct values, and a question about missing
    data.
    """
    scope = " ".join(_rule("default_to_active")["scope"].split())
    for carve_out in ("states a status", "every status", "distributed across",
                      "distinct", "missing"):
        assert carve_out in scope, f"scope does not exclude {carve_out!r}"


def test_the_word_all_on_its_own_does_not_switch_the_default_off():
    """"Show me all my tasks" still means the ones still to do.

    The spec is explicit that "show me all orders" follows the active-first
    behaviour, and people use "all" as filler rather than as a request for
    closed records. An earlier draft of this rule listed "all initiatives" as
    an escape, which would have inverted exactly the case the spec calls out.
    """
    scope = " ".join(_rule("default_to_active")["scope"].split())
    assert '"all" on its own is NOT such a request' in scope
    assert '"all initiatives"' not in scope, "bare 'all' is offered as an escape again"


def test_the_default_is_a_policy_not_a_togglable_filter():
    """It must not become a suggestion button.

    followup._rule_predicates turns every single-equality rule into an "Only
    the active ones" action. This default is already in force, so offering it
    would be offering a no-op -- and the rule carries no sql_fragment
    precisely so it cannot be read that way.
    """
    from pipeline.followup import _rule_predicates

    assert "sql_fragment" not in _rule("default_to_active")
    assert "default_to_active" not in [name for name, *_ in _rule_predicates()]


def test_the_default_reaches_the_model_in_the_built_prompt():
    """Rendered, not merely present on disk.

    _render_rules emits name, definition, sql_fragment and scope and nothing
    else, so a rule whose content lived in any other key would pass the tests
    above and still never be read by the model.
    """
    from claude.prompts import build_lean_system_prompt

    prompt = build_lean_system_prompt()
    assert "default_to_active" in prompt
    assert "business_object_status = 'Active'" in prompt
    assert "task_status = 'open'" in prompt
