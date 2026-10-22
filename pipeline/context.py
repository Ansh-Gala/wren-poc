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


def subject_nouns() -> frozenset[str]:
    """The words that name a subject rather than describe one: every entity's
    words in product.yaml.

    A missing one is not theoretical: "what attachments do we have?" once
    named no subject this set recognised, so it read as a follow-up and was
    answered with the previous question's filters still in force -- a
    narrower answer than the question, and nothing downstream could tell.
    """
    from pipeline.metadata import profile

    return frozenset(profile().subject_nouns())

# A request that stands on its own opens with a verb of asking...
_REQUEST_VERB = re.compile(
    r"^\s*(show|list|give|get|display|find|tell|fetch|pull)\b", re.IGNORECASE)

# ...or is a wh-question. Any wh-opener counts, not only one followed by an
# auxiliary: "which roles BELONG to sales" and "who OWNS this initiative" are
# whole questions too, and read as fragments each inherited the previous
# turn's filters and came back quietly narrower than it was asked.
#
# Left loose deliberately. is_complete_request consults it only after a subject
# noun has already been found, and the referential and elliptical forms are
# tested before it -- so "what about tasks" and "which ones are delayed" are
# settled earlier and never reach here.
_WH_OPENER = re.compile(
    r"^\s*(how many|how much|which|what|who|whose|when|where)\b", re.IGNORECASE)


def is_complete_request(question: str) -> bool:
    """Whether the question names its own subject and asks for it outright.

    Both halves are needed. "Show their status too" opens with a verb of
    asking but names no subject, so it continues the thread; "How many tasks?"
    names tasks and asks outright, so it stands alone. Only when both are
    present is the turn independent of what came before -- which is what makes
    it safe to drop the filters that were narrowing the previous subject.
    """
    nouns = subject_nouns()
    if not any(token in nouns for token in _tokens(question)):
        return False
    return bool(_REQUEST_VERB.match(question) or _WH_OPENER.match(question))


def _is_identifier_column(column: str) -> bool:
    """Whether a column name identifies a row rather than describes one: an
    entity's id in product.yaml under any of its names, or a name with one of
    its id_column_endings."""
    from pipeline.metadata import profile

    column = (column or "").lower()
    if column in {name.lower() for name in profile().identifier_columns()}:
        return True
    return any(ending and column.endswith(ending.lower()) for ending in profile().id_endings())


def _equality_value(column: str, predicate: str) -> str | None:
    """The literal an equality predicate compares a column to, or None.

    Anchored on the whole predicate so only ``x = 'y'`` or ``x = 12`` matches.
    An inequality, a range, a LIKE or an IN all fall through, which is the
    point: none of them is a question about one record. Nor does a column on
    the right -- ``t.initiative_id = i.initiative_id`` is a join, and reading
    it as a subject put "initiative i.initiative_id" in a public pill.
    """
    pattern = (
        r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
        + re.escape(column)
        + r"\s*=\s*(?:'([^']*)'|(-?\d+(?:\.\d+)?))\s*$"
    )
    found = re.match(pattern, str(predicate), re.IGNORECASE)
    if not found:
        return None
    return (found.group(1) if found.group(1) is not None else found.group(2)).strip()


def _subject_noun(column: str) -> str:
    """What to call the thing an identifier column identifies.

    One record, one name. Older SQL called the initiative bo_id or
    business_object_id, so a thread that met both would otherwise rename the
    thing under discussion partway through -- "initiative 123" on one turn and
    "BO 123" on the next, which reads as two subjects and compares as a change
    of subject. So an entity's id, under any of its names in product.yaml,
    is called by the entity's name.
    """
    from pipeline.labels import column_phrase
    from pipeline.metadata import profile

    record = profile().record_name(column)
    if record is not None:
        return record
    words = [w for w in column_phrase(column).split(" ") if w]
    while words and words[-1].lower() in ("id", "ref"):
        words.pop()
    return " ".join(words) if words else str(column)


def _subject_from(filters: dict) -> dict | None:
    """The one record a query is about, if it is about one.

    Read off an equality on an identifier column, because that is what "about
    one thing" looks like in SQL. Only an equality counts: ``task_id IN
    (1,2,3)`` is a list, and browsing a list must not pin the thread to a row.

    Identifier-ness is decided by product.yaml: the entities' ids, and the
    id_column_endings naming convention, which covers a table nobody has
    added yet.

    The first match wins when a query names two. That is a guess, and a wrong
    one is visible and removable in the context bar rather than silent.
    """
    for column, predicate in (filters or {}).items():
        if not _is_identifier_column(column):
            continue
        value = _equality_value(column, predicate)
        if not value:
            continue
        return {
            "column": column,
            "value": value,
            "label": f"{_subject_noun(column)} {value}".strip(),
        }
    return None


@dataclass
class ConversationState:
    """What the next question needs in order to be understood.

    Deliberately not a transcript. Everything here is either the current
    subject, a constraint still in force, or the immediately previous query --
    the three things a follow-up can refer to.
    """

    # What the user is trying to find out, in their own words.
    #
    # The rest of this class describes the last QUERY -- which tables, which
    # filters, which grouping -- all of it reverse-engineered from the SQL that
    # ran. None of it says what the user wanted, and the question itself used
    # to be thrown away the moment the turn ended. So a thread could keep every
    # filter and still forget the point: asked which departments were
    # performing poorly, the system would carry task_status = 'open' forward
    # and lose "performing poorly" entirely.
    #
    # Set from the question that opened the block, including the resolved form
    # after a clarification, so it is never empty while a block is running. The
    # model may replace it with a better statement of the same intent.
    active_goal: str | None = None

    # The particular record under discussion, if there is one: one row, such
    # as initiative 123 or task 4711.
    #
    # Kept apart from active_filters because it obeys a different rule. Filters
    # are replaced wholesale from each new query, deliberately, so they can be
    # dropped. A subject must not work that way: "who owns it" then "what tasks
    # are in it" produce queries that need not repeat the id, and under the
    # filter rule the thing being discussed would vanish on the first turn that
    # did not mention it.
    #
    # Shape: {"column": "business_object_id", "value": "123",
    #         "label": "initiative 123"}.
    active_subject: dict | None = None

    active_tables: list[str] = field(default_factory=list)
    active_filters: dict[str, str] = field(default_factory=dict)
    active_grouping: list[str] = field(default_factory=list)
    active_sorting: str | None = None
    active_limit: int | None = None
    last_intent: str = ""
    previous_sql: str | None = None
    previous_result_summary: str = ""
    turns_in_block: int = 0

    # What the conversation has been about, in the model's own words, folded
    # afresh each turn rather than added to. The structured fields above are
    # exact and lossy: they hold the last query's shape and nothing of why it
    # was asked. This holds the why, and with recent_questions survives a
    # change of subject -- which is the point, since that is when the fields
    # are cleared and the thread would otherwise start from nothing.
    rolling_recap: str | None = None

    # The user's own recent questions, oldest first. The safety net under the
    # recap: a summary can lose the detail that "last week" was ever asked
    # for, and "no, I meant all of them" needs that detail to be resolvable.
    #
    # These are the user's words, so they disclose nothing the user did not
    # type. The risk they carry is different: a question that named a filter
    # the user has since dropped can invite the model to re-apply it. The
    # recap is what answers that, by saying the restriction was removed.
    recent_questions: list[str] = field(default_factory=list)

    pending_clarification: object | None = None
    pending_question: str = ""
    # A clarifying question the system asked in prose, with no candidates to
    # choose from. Entity clarifications resolve by matching the reply against
    # what was offered; these have nothing to match, so the question itself has
    # to reach the next turn or the reply is meaningless.
    awaiting_answer_to: str | None = None
    # Filters the user took off by hand this turn (the Drupal port's context
    # pills). Named to the model for this one turn: left to the question's
    # wording, the open-by-default rule put a dropped status filter back.
    # Cleared once the context block is built, so it never reaches a later
    # turn.
    dropped_filters: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.previous_sql is None

    def reset(self) -> None:
        """Begin a new conversational block, keeping nothing."""
        self.active_goal = None
        self.active_subject = None
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
        # rolling_recap and recent_questions are deliberately NOT cleared
        # here.
        # reset() runs on a new block or a change of subject, and dropping the
        # filters is exactly what that is for -- a filter can silently narrow
        # an answer. The recap cannot: it holds no predicate and no SQL. A
        # user who asks about one initiative, then another, then "how do those
        # two compare?" is asking a question only the recap can carry.

    def forget_history(self) -> None:
        """Drop the carried conversation as well as the block.

        For an explicit "new topic" / "forget that", where the user has said
        the thread is over. Nothing inferred reaches this: a switch the
        classifier noticed is not the user asking to be forgotten.
        """
        self.rolling_recap = None
        self.recent_questions = []


from pipeline.redact import names_a_database_object

NEWLINE = chr(10)

# A verbatim window of the last K exchanges was built here and taken out
# again, which is worth recording so that it is not rebuilt.
#
# It cannot be made safe in this system. A user who drops a constraint --
# "forget the department, all of them" -- classifies as an ordinary follow-up,
# so the earlier question "open tasks for Sales" would still be in the window
# on the very turn that removed it, and a model reading it has every reason to
# go on filtering. The answer side is no safer: `explanation` is specified to
# read "the open tasks for the Sales department this month". Two tests guard
# this exact failure on purpose.
#
# The recap does not have the problem, because it is not a transcript. It is
# folded afresh every turn, so the turn that drops the department produces a
# recap without one. That is the property a window structurally cannot have,
# and it is why the recap, with the user's own recent questions, is what
# carries forward -- never the model's answers or SQL.
RECAP_MAX_CHARS = 320

# How many of the user's own questions travel, and how much of each.
#
# Ten, because that is roughly as far back as anyone says "the one before
# that" about, and because it costs almost nothing: real questions here
# average 43 characters, so ten of them is about 110 tokens.
RECENT_QUESTIONS = 10
RECENT_QUESTION_CHARS = 160

# The identifier guard lives in one place. It used to be copied here, on the
# argument that this module should not depend on the boundary -- but three
# copies is how a guard starts disagreeing with itself about what a database
# name looks like, and one of them silently missing a rule is exactly the
# failure being guarded against.


def _clip(text: str | None, limit: int) -> str:
    """Flatten and shorten, on a word boundary where one is near the end."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rstrip()
    space = cut.rfind(" ")
    if space > limit - 30:
        cut = cut[:space]
    return cut + "..."


def accept_recap(text: str | None) -> str | None:
    """The model's summary of the thread, if it is fit to keep.

    ``None`` means keep whatever is already there -- never blank it. A recap
    that trips a tell is one bad sentence, and erasing the thread over it
    would make the model's worst turn the one that decides what is
    remembered.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return None
    if names_a_database_object(flat):
        return None
    return _clip(flat, RECAP_MAX_CHARS)


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

    # Every comparison in WHERE whose left side is a plain column, keyed by
    # column; a later one on the same column overwrites an earlier one, as
    # Drupal's SqlReader does. A filter the next turn might replace has to be
    # addressable by column name.
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
    elif any(s.find(exp.AggFunc) is not None for s in selects if s is not None):
        intent = "aggregate"

    return {
        "tables": tables, "filters": filters, "grouping": grouping,
        "sorting": sorting, "limit": limit, "intent": intent,
    }


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t]


def classify_turn(question: str, state: ConversationState) -> str:
    """Decide whether this question continues the block or starts a new one.

    Returns one of:
      new_block  -- unrelated subject, or the user said so outright
      follow_up  -- refines what is already on the table

    A change of subject inside a follow-up ("what about AR_PD_Suiting?") is
    left to the model, which sees the filters in force and the question.

    Done without an LLM call on purpose. The signals are unambiguous enough to
    decide deterministically, and a model call here would cost more than the
    context it saves and could itself be wrong.
    """
    if _EXPLICIT_RESET.search(question) or state.is_empty():
        return "new_block"

    # Anaphora or an elliptical opener means it leans on the previous turn.
    if _REFERENTIAL.search(question) or _ELLIPTICAL.match(question):
        return "follow_up"

    # No referential cue. What separates "Show my active tasks" from "Show
    # their status too" is not length -- both are four words -- but whether
    # the question names a subject of its own.
    if is_complete_request(question):
        return "new_block"
    return "follow_up"


def update_state(
    state: ConversationState,
    question: str,
    sql: str | None,
    row_count: int | None,
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
    if decision == "new_block":
        state.reset()

    # The goal is set exactly once per block. reset() clears it, so this fires
    # on the turn that opens a block and never again -- which is what makes it
    # survive follow-ups instead of being overwritten by "only the delayed
    # ones", a phrase that states no goal at all.
    if state.active_goal is None and (question or "").strip():
        state.active_goal = " ".join(str(question).split())

    parsed = parse_sql_state(sql or "")
    if parsed["tables"]:
        state.active_tables = parsed["tables"]
    state.active_filters = dict(parsed["filters"])
    # Assigned, never cleared. The line above replaces every filter from the
    # query that just ran -- deliberately, so a filter can be dropped by asking
    # -- and the record under discussion must not obey that rule. "Who owns it"
    # and "what tasks are in it" are answered by queries that need not repeat
    # the id, and under the filter rule the thing being discussed would
    # disappear on the first turn that failed to mention it.
    subject = _subject_from(parsed["filters"])
    if subject is not None:
        # A different record means the goal that named the old one is no longer
        # what the user is after. Compared on the label rather than the value,
        # because the value alone is not an identity: task 123 and initiative
        # 123 share a number and are not the same thing.
        changed = (
            state.active_subject is not None
            and state.active_subject.get("label") != subject["label"]
        )
        if changed and (question or "").strip():
            state.active_goal = " ".join(str(question).split())
        state.active_subject = subject
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


def remember_question(state: ConversationState, question: str) -> None:
    """Add the user's question to the window, and drop anything past the bound."""
    flat = _clip(question, RECENT_QUESTION_CHARS)
    if not flat:
        return
    state.recent_questions.append(flat)
    if len(state.recent_questions) > RECENT_QUESTIONS:
        del state.recent_questions[:-RECENT_QUESTIONS]


def render_context(state: ConversationState) -> str:
    """What the model is told about the conversation so far.

    Two things, and deliberately nothing else: a short account of what the
    user currently means, and their own recent questions.

    What is NOT here used to be the bulk of it -- the filters in force, the
    tables, the pinned subject, the grouping, the previous query. All of that
    is still tracked, because the suggestion chips are built from it, but none
    of it reaches the model any more. It was this module deciding what the
    question meant and handing over its conclusions; the model reads a
    conversation better than a SQL parser does, and every one of those lines
    was also a database detail travelling one step closer to the user.

    The one exception is a question the system itself asked and is waiting on.
    That is not derived context -- it is an open question, and a reply of
    "both" cannot be read without it.
    """
    lines: list[str] = []

    # First, because it changes what the whole turn means: the user is
    # replying to something, and "both" is only interpretable against the
    # question that prompted it.
    if state.awaiting_answer_to:
        lines.append("YOU ASKED THE USER THIS, AND THE QUESTION BELOW MAY BE THEIR ANSWER")
        lines.append(f"  {' '.join(state.awaiting_answer_to.split())}")
        # "IS their answer" was too strong. Asked to choose between listing
        # and grouping, a user replied "3", and the turn came back as LIMIT 3
        # -- valid SQL and an invention.
        lines.append("  If it does not answer that, ask again instead of choosing an")
        lines.append("  interpretation. A reply matching none of what you asked is not")
        lines.append("  an answer to it.")

    # The other exception: a filter the user removed by hand. Left to the
    # question's wording, the model put a dropped "task_status = 'open'" back
    # in 4 of 10 runs, because the active-first rule re-adds it by default.
    if state.dropped_filters:
        if lines:
            lines.append("")
        lines.append("THE USER JUST REMOVED THIS FILTER")
        for predicate in state.dropped_filters:
            lines.append(f"  {predicate}")
        lines.append("  Leave it out of the query. Do not add it back, not even as a default.")

    if state.rolling_recap:
        if lines:
            lines.append("")
        lines.append("CONTEXT")
        lines.append(f"  {state.rolling_recap}")

    # The whole window. The question being asked right now is not in it yet --
    # run_turn appends it after this block is built, precisely so that a
    # question never appears in its own history.
    if state.recent_questions:
        if lines:
            lines.append("")
        lines.append("RECENT QUESTIONS (oldest first)")
        for question in state.recent_questions:
            lines.append(f"  {question}")

    if not lines:
        return ""
    return NEWLINE.join(["ACTIVE CONVERSATION CONTEXT", ""] + lines + [""])


# The static half of the conversational contract. It never changes, so it
# belongs in the cached system prompt rather than being re-sent with every
# turn: about 350 tokens a question, for text identical on turn 1 and turn 20.
#
# Splitting it out is also what makes the per-turn block genuinely small --
# without this, "compact context" would still have been mostly boilerplate.
CONTEXT_GUIDANCE = """When an ACTIVE CONVERSATION CONTEXT block is present, the question continues
that conversation. Resolve references such as "those", "them", "the active
ones" or "how many?" against it.

CONTEXT is one or two sentences saying what the user currently means, carried
from the previous turn and rewritten each time. Treat it as the state of the
conversation, not as a filter: it says what is being discussed, and when it
says a restriction was removed, it has been removed.

RECENT QUESTIONS are the user's own words, oldest first, ending with the one
before this. They are there for the times the summary is not enough -- "no, I
meant the previous one", "remove the date filter", "same thing but for
{other_subject}". Read them to work out what the current question refers to. Do NOT
treat them as still in force: a filter someone asked for four questions ago is
only still wanted if the CONTEXT says so.

Work out for yourself how this question relates to what came before, and write
the query it asks for. Nothing in the block is a template to copy."""
