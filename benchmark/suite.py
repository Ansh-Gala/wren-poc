"""Load a lean suite from YAML into the shapes pipeline/lean_suite.py defines.

Split from those shapes deliberately. The HTTP runtime builds a SuiteTurn per
request and never reads a suite file, so putting the loader here means a
production checkout does not need a question set -- or a path pointing at one
-- to exist.

Both YAML shapes load into the same object: an entry with a `turns` list
becomes a conversation of that length, an entry without one becomes a
conversation of length one.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.lean_suite import (
    BEHAVIOURS, Conversation, DECISIONS, FOLLOWUPS, SuiteTurn,
)

SUITE_FILE = Path(__file__).resolve().parent / "lean_questions.yaml"


def _turn(raw: dict, conv_id: str, index: int, default_category: str) -> SuiteTurn:
    decision = raw.get("expect_decision")
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"{raw.get('id')}: expect_decision must be one of {DECISIONS}")
    behavior = raw.get("expect_behavior", "sql")
    if behavior not in BEHAVIOURS:
        raise ValueError(f"{raw.get('id')}: expect_behavior must be one of {BEHAVIOURS}")
    followup = raw.get("expect_followup")
    if followup is not None and followup not in FOLLOWUPS:
        raise ValueError(f"{raw.get('id')}: expect_followup must be one of {FOLLOWUPS}")
    normalized = raw.get("expect_normalized")
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
        expect_columns=[list(group) if isinstance(group, (list, tuple)) else [group]
                        for group in (raw.get("expect_columns") or [])],
        note=raw.get("note"),
        expect_normalized=" ".join(normalized.split()) if normalized else None,
        expect_followup=followup,
        expect_action=raw.get("expect_action"),
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
