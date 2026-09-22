"""Which column a business word means, when more than one could fit.

Two questions the schema alone cannot settle, because both readings are
grammatical and only one is what people mean.

"Initiative 202" names an initiative by a number, and the table holds two
numbers that could be it. The worked examples used to answer with the
reference identifier, and the model copied them -- an example is the
strongest thing in the prompt, so an example that teaches the wrong column
cannot be corrected by a description that teaches the right one.

"Unassigned" sounds like absence, and absence in SQL is NULL. Here it is not:
the TMS writes the text 'NA' and never leaves the column empty, so the
reading that looks obvious returns nothing at all.

These are asserted against the metadata rather than against generated SQL
because the metadata is what the model is shown, and a live call would test
the model rather than this repository.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from claude.prompts import build_lean_system_prompt

META_DIR = Path(__file__).resolve().parents[1] / "metadata"


def _load(name: str) -> dict:
    return yaml.safe_load((META_DIR / name).read_text(encoding="utf-8")) or {}


@pytest.fixture(scope="module")
def pairs() -> list[dict]:
    return _load("question_sql_pairs.yaml")["pairs"]


@pytest.fixture(scope="module")
def rules() -> dict[str, dict]:
    return {r["name"]: r for r in _load("business_rules.yaml")["rules"]}


@pytest.fixture(scope="module")
def columns() -> dict[str, dict]:
    doc = _load("schema_description.yaml")
    return {
        table: spec.get("columns") or {}
        for table, spec in (doc.get("tables") or {}).items()
    }


# ----------------------------------------------------- "initiative 202" --

def test_no_worked_example_matches_an_initiative_number_on_the_reference(pairs):
    """The example is the lesson. One teaching the reference teaches it hardest."""
    offenders = [
        p["nl"] for p in pairs
        if re.search(r"initiative_ref_id\s*=\s*'\d+'", p["sql"])
    ]
    assert offenders == [], f"these teach the reference column: {offenders}"


def test_an_example_matches_an_initiative_number_on_the_id(pairs):
    assert any(re.search(r"\binitiative_id\s*=\s*\d+", p["sql"]) for p in pairs)


def test_the_id_is_unquoted_because_it_is_an_integer(pairs):
    """A quoted integer is a type error waiting for a stricter comparison."""
    for p in pairs:
        assert not re.search(r"\binitiative_id\s*=\s*'", p["sql"]), p["nl"]


def test_a_rule_says_which_identifier_a_bare_number_means(rules):
    rule = rules["initiative_identifier"]
    text = rule["definition"]
    assert "initiative_id" in text
    assert "initiative_ref_id" in text
    # And it must say when the reference IS right, or it reads as a ban.
    assert "reference" in text.lower()


def test_the_two_identifier_columns_say_which_is_which(columns):
    initiative = columns["tms_initiative_flat"]
    assert "initiative_id = 202" in initiative["initiative_id"]["description"]
    assert "only" in initiative["initiative_ref_id"]["description"].lower()


# ------------------------------------------------------------ "unassigned" --

def test_a_rule_defines_an_unassigned_task(rules):
    assert "unassigned_task" in rules


def test_the_rule_names_the_value_that_is_actually_stored(rules):
    assert "'NA'" in rules["unassigned_task"]["definition"]


def test_the_rule_rules_out_the_reading_that_returns_nothing(rules):
    """assigned_user_name is never null, so IS NULL is silently always empty."""
    assert "IS NULL" in rules["unassigned_task"]["definition"]


def test_the_rule_covers_the_ways_people_say_it(rules):
    text = rules["unassigned_task"]["definition"].lower()
    for phrasing in ("unassigned", "not assigned", "nobody"):
        assert phrasing in text, phrasing


def test_the_column_itself_says_na_is_a_value_and_not_a_gap(columns):
    description = columns["tms_task_flat"]["assigned_user_name"]["description"]
    assert "'NA'" in description
    assert "null" in description.lower()


def test_the_unassigned_rule_offers_no_toggleable_filter(rules):
    """A single-equality fragment becomes a chip reading "Only the na ones".

    The rule earns its place in the prompt; it does not earn a chip. Rules
    that are not a filter a person would toggle carry no sql_fragment, which
    is how followup._rule_predicates skips them.
    """
    assert "sql_fragment" not in rules["unassigned_task"]


# ------------------------------------------------ and all of it is shown --

@pytest.mark.parametrize("needle", [
    "unassigned_task",
    "initiative_identifier",
    "'NA'",
    "initiative_id = 202",
])
def test_the_model_is_actually_shown_this(needle):
    """Metadata the prompt renderer drops is metadata that does nothing."""
    assert needle in build_lean_system_prompt()
