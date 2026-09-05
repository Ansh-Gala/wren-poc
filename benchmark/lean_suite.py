"""Loader for the lean suite, where a question may be one turn of a thread.

The existing questions.yaml is a flat list: every entry stands alone. That
cannot express "only the active ones", whose meaning depends entirely on what
came before it, so the lean suite adds a second shape.

Both shapes load into the same object. A standalone question is simply a
conversation of length one, which lets the runner keep a single loop and
guarantees a standalone question gets a genuinely empty context rather than
whatever the previous question left behind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SUITE_FILE = Path(__file__).resolve().parent / "lean_questions.yaml"

# What the session layer should decide for a turn. Asserted alongside the SQL,
# because a thread can produce the right answer while classifying the turn
# wrongly, and that would break on the next turn instead of this one.
DECISIONS = ("new_block", "follow_up", "switch", "rebase")

# What the turn should produce.
#   sql      -- a query (the default)
#   clarify  -- the question cannot or should not be answered as asked, and the
#               system should say so rather than guess. Without this the only
#               way to score "should not guess" is to hope the model fails.
#   zero_or_clarify
#            -- the question names a value the column does not have (colour
#               "Purple", unit "unit9"). Two answers are defensible: run the
#               query and return nothing, or point out that the value does not
#               exist. Both are accepted. What is not accepted is substituting
#               a value that does exist in order to return rows, which is how
#               "no results" silently becomes a confident wrong answer.
BEHAVIOURS = ("sql", "clarify", "zero_or_clarify")


@dataclass(frozen=True)
class SuiteTurn:
    id: str
    question: str
    expected_sql: str | None
    category: str
    conversation_id: str
    turn_index: int
    ordered: bool = False
    tags: list[str] = field(default_factory=list)
    expect_decision: str | None = None
    expect_behavior: str = "sql"
    # True when the question names its output columns, so a different column
    # list is a real error rather than a different reasonable choice.
    strict_projection: bool = False
    note: str | None = None

    @property
    def is_standalone(self) -> bool:
        return self.turn_index == 0


@dataclass(frozen=True)
class Conversation:
    id: str
    category: str
    turns: list[SuiteTurn]

    @property
    def is_standalone(self) -> bool:
        return len(self.turns) == 1


def _turn(raw: dict, conv_id: str, index: int, default_category: str) -> SuiteTurn:
    decision = raw.get("expect_decision")
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"{raw.get('id')}: expect_decision must be one of {DECISIONS}")
    behavior = raw.get("expect_behavior", "sql")
    if behavior not in BEHAVIOURS:
        raise ValueError(f"{raw.get('id')}: expect_behavior must be one of {BEHAVIOURS}")
    sql = raw.get("expected_sql")
    return SuiteTurn(
        id=raw["id"],
        question=" ".join(raw["question"].split()),
        expected_sql=sql.strip() if sql is not None else None,
        category=raw.get("category", default_category),
        conversation_id=conv_id,
        turn_index=index,
        ordered=bool(raw.get("ordered", False)),
        tags=list(raw.get("tags", []) or []),
        expect_decision=decision,
        expect_behavior=behavior,
        strict_projection=bool(raw.get("strict_projection", False)),
        note=raw.get("note"),
    )


def load_suite(path: Path | None = None) -> list[Conversation]:
    doc = yaml.safe_load((path or SUITE_FILE).read_text(encoding="utf-8"))
    conversations: list[Conversation] = []

    for raw in doc.get("questions", []) or []:
        category = raw.get("category", "")
        if "turns" in raw:
            turns = [
                _turn(t, raw["id"], i, category)
                for i, t in enumerate(raw["turns"])
            ]
            if not turns:
                raise ValueError(f"{raw['id']}: conversation has no turns")
            conversations.append(Conversation(raw["id"], category, turns))
        else:
            conversations.append(
                Conversation(raw["id"], category, [_turn(raw, raw["id"], 0, category)])
            )

    ids = [t.id for c in conversations for t in c.turns]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate turn ids: {sorted(duplicates)}")
    return conversations


def all_turns(conversations: list[Conversation]) -> list[SuiteTurn]:
    return [t for c in conversations for t in c.turns]


def select(
    conversations: list[Conversation],
    ids: list[str] | None = None,
    categories: str | None = None,
) -> list[Conversation]:
    """Filter whole conversations.

    Selection is by conversation, never by individual turn: running turn 3 of
    a thread without turns 1 and 2 would test nothing, since its context would
    be empty.
    """
    selected = conversations
    if ids:
        wanted = {i.upper() for i in ids}
        selected = [
            c for c in selected
            if c.id.upper() in wanted or any(t.id.upper() in wanted for t in c.turns)
        ]
    if categories:
        wanted = {c.strip().upper() for c in categories.split(",") if c.strip()}
        selected = [c for c in selected if c.category.upper() in wanted]
    return selected
