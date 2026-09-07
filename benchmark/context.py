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


# The words that name a subject rather than describe one. Taken from the table
# names (tms_business_object_flat, tms_task_flat, tms_user_flat, tms_role_flat)
# and from the entity_alias business rule, which declares Initiative, Order, BO
# and Business Object to be one entity. "item" is the word the benchmark and
# the users actually use for a business object.
_SUBJECT_NOUNS = frozenset("""
task tasks item items object objects initiative initiatives order orders
user users role roles workflow workflows department departments
""".split())

# A request that stands on its own opens with a verb of asking...
_REQUEST_VERB = re.compile(
    r"^\s*(show|list|give|get|display|find|tell|fetch|pull)\b", re.IGNORECASE)

# ...or is a wh-question with a clause of its own. The trailing verb is what
# separates "How many tasks are open?", which is a whole question, from "How
# many tasks?", which is still leaning on the turn before it.
_WH_CLAUSE = re.compile(
    r"^\s*(how many|how much|which|what|who|when|where)\b.*"
    r"\b(is|are|was|were|have|has|had|do|does|did|can)\b",
    re.IGNORECASE,
)


def is_complete_request(question: str) -> bool:
    """Whether the question names its own subject and asks for it outright.

    Both halves are needed. "Show their status too" opens with a verb of
    asking but names no subject, so it continues the thread; "How many tasks?"
    names one but does not ask a whole question. Only when both are present is
    the turn independent of what came before -- which is what makes it safe to
    drop the filters that were narrowing the previous subject.
    """
    if not any(token in _SUBJECT_NOUNS for token in _tokens(question)):
        return False
    return bool(_REQUEST_VERB.match(question) or _WH_CLAUSE.match(question))


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

    # A question the system asked and is waiting on, with the choices it
    # offered. Held here because it is exactly what the next turn needs in
    # order to be understood -- "AR_YD_Suiting" means nothing without it. Not
    # rendered into the prompt: it is resolved before the model is asked, so
    # what the model sees is the original question with the choice filled in.
    pending_clarification: object | None = None
    pending_question: str = ""
    # A clarifying question the system asked in prose, with no candidates to
    # choose from. Entity clarifications resolve by matching the reply against
    # what was offered; these have nothing to match, so the question itself has
    # to reach the next turn or the reply is meaningless.
    awaiting_answer_to: str | None = None

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
        self.pending_clarification = None
        self.pending_question = ""
        self.awaiting_answer_to = None


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
      switch     -- a different subject, stated in full, so the old state goes
      rebase     -- a different subject named elliptically ("what about X?"),
                    which swaps the subject but keeps the question's shape
      follow_up  -- refines what is already on the table

    The distinction between switch and rebase matters. "Show AR_NPD_Shirting
    items" after filtering the previous subject to Active is a fresh request
    and must not inherit Active. "What about AR_PD_Suiting?" after "how many
    delayed tasks?" is the same question about a different subject, and
    discarding the state leaves nothing to answer -- the system can only ask
    what was meant, which is what it did before this case was separated out.

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
    # even mid-conversation -- unless it arrives elliptically, in which case
    # only the subject changes and everything else was meant to carry.
    if named and state.active_entity and named != state.active_entity:
        # Only the elliptical form rebases. Length is not the discriminator:
        # "Show AR_NPD_Shirting items" is four words and still a complete
        # request that carries its own shape, so it starts clean.
        if _ELLIPTICAL.match(question):
            return "rebase", named
        return "switch", named
    if named and not state.active_entity:
        return "follow_up", named
    if named:
        return "follow_up", named

    # No subject named. Anaphora or an elliptical opener means it leans on the
    # previous turn.
    if _REFERENTIAL.search(question) or _ELLIPTICAL.match(question):
        return "follow_up", state.active_entity

    # No subject and no referential cue. What separates "Show my active tasks"
    # from "Show their status too" is not length -- both are four words -- but
    # whether the question names a subject of its own.
    if is_complete_request(question):
        return "new_block", None
    return "follow_up", state.active_entity


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
    elif decision == "rebase":
        # Keep the shape, drop only what identified the old subject.
        state.active_filters = {
            col: pred for col, pred in state.active_filters.items()
            if state.active_entity is None or state.active_entity not in pred
        }
        state.turns_in_block = 0

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
    if state.is_empty() and not state.awaiting_answer_to:
        return ""

    lines = ["ACTIVE CONVERSATION CONTEXT", ""]

    # First, because it changes what the whole turn means: the user is
    # replying to something, and "both" or "mail" is only interpretable
    # against the question that prompted it.
    if state.awaiting_answer_to:
        lines.append("YOU ASKED THE USER THIS, AND THE QUESTION BELOW IS THEIR ANSWER")
        lines.append(f"  {' '.join(state.awaiting_answer_to.split())}")
        lines.append("")

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
