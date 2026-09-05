"""Conversation state for follow-up questions.

The naive way to support "only the active ones" is to replay the whole
conversation into the prompt. That works, but it grows without bound: every
turn adds its question and its SQL, so a 20-turn session pays for 20 turns of
history on turn 20, and most of it is stale by then.

What actually decides the meaning of the next question is much smaller: which
entity is being talked about, which filters are currently in force, and what
the last query was. That set does not grow with turn count. This module keeps
it as structured state, updated from the SQL the model actually produced
rather than from a second guess about what it meant.

Turn 1 and turn 20 therefore cost the same.

The SQL is parsed with sqlglot, the same parser the read-only gate uses, so
the state reflects the query that ran rather than a regex approximation of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

# A follow-up cannot be recognised by length alone: "How many?" is one, and
# "How many AR_NPD_Shirting items are there?" is not, though both are short.
# What separates them is whether the question names a subject of its own.
#
# Anaphora that can only be resolved against earlier turns.
_REFERENTIAL = re.compile(
    r"\b(those|these|them|they|it|that one|the ones|the first ones|"
    r"the active ones|the closed ones|the open ones|same|previous|above)\b",
    re.IGNORECASE,
)

# Openers that are meaningless standing alone, so they must be continuations.
_ELLIPTICAL = re.compile(
    r"^\s*(and\s+|but\s+|also\s+|now\s+|what about\b|how about\b|only\b|just\b|"
    r"instead\b|remove\b|drop\b|add\b|sort\b|order\b|group\b|limit\b|show more\b|"
    r"more\b|fewer\b|less\b)",
    re.IGNORECASE,
)

# An explicit signal from the user that the thread is over.
_EXPLICIT_RESET = re.compile(
    r"^\s*(new question|new topic|forget that|start over|unrelated|"
    r"changing topic|different question)\b[:,\s]*",
    re.IGNORECASE,
)


def _normalise(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


@dataclass
class ConversationState:
    """What the next question needs in order to be understood.

    Deliberately not a transcript. Everything here is either the current
    subject, a constraint still in force, or the immediately previous query --
    the three things a follow-up can refer to.
    """

    active_entity: str | None = None
    active_tables: list[str] = field(default_factory=list)
    active_filters: dict[str, str] = field(default_factory=dict)
    active_grouping: list[str] = field(default_factory=list)
    active_sorting: str | None = None
    active_limit: int | None = None
    last_intent: str = ""
    previous_sql: str | None = None
    previous_result_summary: str = ""
    turns_in_block: int = 0

    def is_empty(self) -> bool:
        return self.previous_sql is None and not self.active_entity

    def reset(self) -> None:
        """Begin a new conversational block, keeping nothing."""
        self.active_entity = None
        self.active_tables = []
        self.active_filters = {}
        self.active_grouping = []
        self.active_sorting = None
        self.active_limit = None
        self.last_intent = ""
        self.previous_sql = None
        self.previous_result_summary = ""
        self.turns_in_block = 0


def parse_sql_state(sql: str) -> dict:
    """Pull the structured shape out of a SQL statement.

    Returns empty pieces rather than raising: a query that sqlglot cannot
    parse should degrade the context, not abort the conversation.
    """
    empty = {
        "tables": [], "filters": {}, "grouping": [],
        "sorting": None, "limit": None, "intent": "",
    }
    if not sql:
        return empty
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return empty
    if tree is None:
        return empty

    tables = []
    for t in tree.find_all(exp.Table):
        name = t.name
        if name and name not in tables:
            tables.append(name)

    # Only top-level AND-ed equality/IN predicates become remembered filters.
    # A filter the next turn might replace has to be addressable by column
    # name; anything more tangled is left to previous_sql to carry.
    filters: dict[str, str] = {}
    where = tree.args.get("where")
    if where is not None:
        for node in where.find_all(exp.EQ, exp.In, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE):
            col = node.this
            if isinstance(col, exp.Column):
                key = col.name
                try:
                    filters[key] = node.sql(dialect="postgres")
                except Exception:
                    continue

    grouping = []
    group = tree.args.get("group")
    if group is not None:
        for e in group.expressions:
            if isinstance(e, exp.Column):
                grouping.append(e.name)

    sorting = None
    order = tree.args.get("order")
    if order is not None:
        try:
            sorting = ", ".join(o.sql(dialect="postgres") for o in order.expressions)
        except Exception:
            sorting = None

    limit = None
    lim = tree.args.get("limit")
    if lim is not None:
        try:
            limit = int(lim.expression.this)
        except Exception:
            limit = None

    # Intent is what the answer looks like, which is what a follow-up such as
    # "how many?" or "list them" switches between.
    intent = "list"
    selects = tree.selects if hasattr(tree, "selects") else []
    if grouping:
        intent = "breakdown"
    elif any(isinstance(s.find(exp.AggFunc), exp.AggFunc) for s in selects if s is not None):
        intent = "aggregate"

    return {
        "tables": tables, "filters": filters, "grouping": grouping,
        "sorting": sorting, "limit": limit, "intent": intent,
    }


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t]


def detect_entity(question: str, gazetteer: list[str]) -> str | None:
    """The subject the question names outright, if any.

    Matched on token runs, not substrings: the entity value "test" must not
    fire on the word "latest". AR_YD_Suiting, ar_yd_suiting and "AR YD
    Suiting" all tokenise the same, so any spelling of the value resolves.

    An exact hit on the raw text wins first, because business_object_type
    contains case-variant near-duplicates that are genuinely distinct values
    (AR_YD_Shirting and AR_YD_SHIRTING); when the user typed one of them
    verbatim that is the one they meant. Otherwise the longest token run wins,
    so AR_NPD_YD_SHIRTING is not shadowed by AR_YD_Shirting.
    """
    if not question:
        return None

    for value in sorted(gazetteer, key=len, reverse=True):
        if not value:
            continue
        # Bounded on both sides, or "test" fires on "latest".
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", question):
            return value

    haystack = _tokens(question)
    best: str | None = None
    best_len = 0
    for value in gazetteer:
        needle = _tokens(value)
        if not needle or len(needle) <= best_len:
            continue
        for i in range(len(haystack) - len(needle) + 1):
            if haystack[i:i + len(needle)] == needle:
                best, best_len = value, len(needle)
                break
    return best


def classify_turn(
    question: str,
    state: ConversationState,
    gazetteer: list[str],
) -> tuple[str, str | None]:
    """Decide whether this question continues the block or starts a new one.

    Returns (decision, entity) where decision is one of:
      new_block  -- unrelated subject, or the user said so outright
      switch     -- a different known entity, so the old filters are stale
      follow_up  -- refines what is already on the table

    Done without an LLM call on purpose. The signals are unambiguous enough to
    decide deterministically, and a model call here would cost more than the
    context it saves and could itself be wrong.
    """
    if _EXPLICIT_RESET.search(question):
        return "new_block", detect_entity(question, gazetteer)

    if state.is_empty():
        return "new_block", detect_entity(question, gazetteer)

    named = detect_entity(question, gazetteer)

    # A different subject invalidates the filters that were narrowing the old
    # one. "Show AR_NPD_Shirting items" after AR_YD_Suiting is a new subject,
    # even mid-conversation.
    if named and state.active_entity and named != state.active_entity:
        return "switch", named
    if named and not state.active_entity:
        return "follow_up", named
    if named:
        return "follow_up", named

    # No subject named. Anaphora or an elliptical opener means it leans on the
    # previous turn.
    if _REFERENTIAL.search(question) or _ELLIPTICAL.match(question):
        return "follow_up", state.active_entity

    # No subject and no referential cue. A question that carries its own verb
    # and object ("How many tasks are there?") reads as standalone; a bare
    # fragment ("how many?") does not.
    words = len(question.split())
    if words <= 6:
        return "follow_up", state.active_entity
    return "new_block", None


def update_state(
    state: ConversationState,
    question: str,
    sql: str | None,
    row_count: int | None,
    entity: str | None,
    decision: str,
) -> ConversationState:
    """Fold one completed turn into the state.

    The state is the shape of the last query, not an accumulation over the
    thread. That distinction matters: an earlier version merged each turn's
    filters into the previous set, which made a filter impossible to remove.
    Asked to drop a business-unit filter the model would produce correct SQL
    without it, the merge would keep it anyway, and the next turn would be told
    it was still in force and put it back. Filters only ever grew.

    Since the generated SQL always carries every filter still in force,
    replacing is both simpler and correct: adding, replacing and removing a
    filter all fall out of it with no special case.
    """
    if decision in ("new_block", "switch"):
        state.reset()

    if entity:
        state.active_entity = entity

    parsed = parse_sql_state(sql or "")
    if parsed["tables"]:
        state.active_tables = parsed["tables"]
    state.active_filters = dict(parsed["filters"])
    state.active_grouping = parsed["grouping"]
    state.active_sorting = parsed["sorting"]
    state.active_limit = parsed["limit"]
    if parsed["intent"]:
        state.last_intent = parsed["intent"]

    if sql:
        state.previous_sql = " ".join(sql.split())
    if row_count is not None:
        state.previous_result_summary = f"{row_count} row(s)"
    state.turns_in_block += 1
    return state


def render_context(state: ConversationState) -> str:
    """The context block handed to the model.

    Compact by construction: the fields are a fixed set, so this stays roughly
    the same size on turn 20 as on turn 2.
    """
    if state.is_empty():
        return ""

    lines = ["ACTIVE CONVERSATION CONTEXT", ""]

    # Grouped deliberately: what is selected persists, how it was presented
    # does not, and the headings are the first place that gets read.
    lines.append("WHAT IS SELECTED (persists until the user changes it)")
    if state.active_entity:
        lines.append(f"  subject: {state.active_entity}")
    if state.active_tables:
        lines.append(f"  tables: {', '.join(state.active_tables)}")
    if state.active_filters:
        lines.append("  filters in force:")
        for _, pred in state.active_filters.items():
            lines.append(f"    - {pred}")
    else:
        lines.append("  filters in force: none")

    shape = []
    if state.active_grouping:
        shape.append(f"  grouped by: {', '.join(state.active_grouping)}")
    if state.active_sorting:
        shape.append(f"  sorted by: {state.active_sorting}")
    if state.active_limit is not None:
        shape.append(f"  limit: {state.active_limit}")
    if state.last_intent:
        shape.append(f"  last intent: {state.last_intent}")
    if shape:
        lines.append("")
        lines.append("HOW THE LAST ANSWER WAS PRESENTED (decide this afresh)")
        lines += shape

    if state.previous_result_summary:
        lines.append("")
        lines.append(f"previous result: {state.previous_result_summary}")
    if state.previous_sql:
        lines.append("previous query (for reference, not a template):")
        lines.append(f"  {state.previous_sql}")

    lines.append("")
    return "\n".join(lines)


# The static half of the conversational contract. It never changes, so it
# belongs in the cached system prompt rather than being re-sent with every
# turn: about 350 tokens a question, for text identical on turn 1 and turn 20.
#
# Splitting it out is also what makes the per-turn block genuinely small --
# without this, "compact context" would still have been mostly boilerplate.
CONTEXT_GUIDANCE = """When an ACTIVE CONVERSATION CONTEXT block is present, the question continues
that conversation. Resolve references such as "those", "them", "the active
ones" or "how many?" against it.

Two parts of that context behave differently, and confusing them is the usual
way a thread goes wrong:

  WHAT IS SELECTED -- the subject and the filters in force. These persist.
    Add one when the user narrows, replace it when they name a different value
    for the same field, drop it only when they say so.

  HOW IT IS PRESENTED -- grouping, sorting, limit and the chosen columns.
    These belong to the previous question, not to the conversation. Decide them
    afresh from the new question. In particular, a grouping does NOT carry
    over: "list them" or "show them" after a GROUP BY means plain rows again,
    and "how many?" means a single count, not the previous grouped result.
    Carry a sort or a limit forward only while the user is still refining the
    same list.

Write the query the new question asks for. The previous query is context, not
a template to copy.
"""
