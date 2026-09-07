"""The shape of one turn, where a question may be one turn of a thread.

A flat list of questions -- benchmark/questions.yaml -- cannot express "only
the active ones", whose meaning depends entirely on what came before it. So a
turn carries its position in a conversation, and a standalone question is
simply a conversation of length one. That lets the runner keep a single loop
and guarantees a standalone question gets a genuinely empty context rather
than whatever the previous question left behind.

Shapes only: no YAML, no file paths, nothing that reads from disk. Two very
different callers build these. The benchmark loads them from a suite file
(benchmark/suite.py); the HTTP runtime constructs one per request with no
expected SQL at all, because a real question has no known-correct answer. The
loader lives on the benchmark side so that the runtime never depends on a
question set existing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What the session layer should decide for a turn. Asserted alongside the SQL,
# because a thread can produce the right answer while classifying the turn
# wrongly, and that would break on the next turn instead of this one.
DECISIONS = ("new_block", "follow_up", "switch", "rebase",
             # The turn answered a question the system asked. The reply is
             # resolved back into the original wording before anything else
             # sees it, so what follows behaves like a fresh block.
             "clarification_response")

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

# What the follow-up layer should offer once the turn is done.
#   clarification -- the turn could not be answered as asked
#   exploration   -- it was answered, and there are obvious next moves
#   none          -- it was answered and stood on its own
#
# Asserted separately from the SQL. A turn can produce a perfect query and
# still offer a useless continuation, and the two failures need different
# fixes, so scoring them together would hide both.
FOLLOWUPS = ("clarification", "exploration", "none")


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

    # -------------------------------------------------- follow-up layer --
    # What the repair layer should make of the question before anything else
    # sees it. Set only where a repair is expected; None means "unchanged".
    expect_normalized: str | None = None
    # Which kind of follow-up should be offered once the turn is done.
    expect_followup: str | None = None
    # The action a suggestion must carry, as a subset of its fields. Checked
    # as a subset rather than an exact match so that adding a field to the
    # contract does not invalidate every case.
    expect_action: dict | None = None

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
