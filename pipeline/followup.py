"""What the system says after -- or instead of -- an answer.

Three things can be worth saying at the end of a turn:

  clarification  the question cannot be answered as asked, and the missing
                 piece is nameable. "Which AR_YD type did you mean?"
  exploration    the question was answered, and there are obvious next moves
                 the user is likely to want. "Only the active ones?"
  none           the answer stood on its own.

Every one of them is decided from state the pipeline already has -- the
structured conversation state, the schema, and the gazetteer generated from
the database. There is no LLM call in this module. That is not a performance
compromise; it is what makes the candidates trustworthy. A model asked to
propose "which order did you mean?" will produce plausible order numbers, and
plausible is exactly wrong. Values offered here can only come from the
database, because there is nowhere else for them to come from.

The output is shaped for a frontend that renders buttons. A suggestion
therefore carries a machine-readable ``action`` alongside its human label, so
the UI never has to parse "Show overdue ones" to work out what it does.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from pipeline.column_order import hidden_names
from pipeline.labels import column_phrase
from pipeline.redact import names_a_database_object

# What a suggestion can ask the system to do. Each maps onto a mutation of
# ConversationState, and from there back through the normal pipeline -- so
# there is still exactly one thing that writes SQL.
ACTION_TYPES = (
    "set_entity",
    "add_filter",
    "replace_filter",
    "remove_filter",
    "add_group_by",
    "set_sort",
    "set_limit",
    "set_aggregate",
    "drill_down",
)

FOLLOWUP_TYPES = ("clarification", "exploration", "none")


@dataclass(frozen=True)
class Action:
    """A state mutation, not SQL.

    Deliberately not SQL: a suggestion that carried its own SQL would be a
    second query generator, and the two would drift.
    """

    type: str
    field: str | None = None
    operator: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ValueError(f"unknown action type {self.type!r}")

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Suggestion:
    id: str
    label: str
    # None for a reading or a next question, which mutate no state: choosing
    # one rewrites the question rather than the filters.
    action: Action | None = None
    # A handle, present only on the chips the model wrote. A label is not a
    # handle -- two readings can read alike, and a chip left on screen from
    # three turns ago sends a label that still matches something -- so the ref
    # says which offer it came from and a stale one resolves against nothing.
    ref: str | None = None

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "label": self.label,
            "action": self.action.to_dict() if self.action else {},
        }
        if self.ref is not None:
            out["ref"] = self.ref
        return out


@dataclass(frozen=True)
class FollowUp:
    type: str
    reason: str
    question: str
    suggestions: list[Suggestion] = field(default_factory=list)
    allow_free_text: bool = True

    @property
    def follow_up_required(self) -> bool:
        return self.type != "none"

    def to_dict(self) -> dict:
        """The wire format. Stable; the frontend is written against this."""
        return {
            "follow_up_required": self.follow_up_required,
            "type": self.type,
            "reason": self.reason,
            "question": self.question,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "allow_free_text": self.allow_free_text,
        }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _value_id(value: str) -> str:
    """An id for a data value, keeping the case the database uses.

    initiative_type holds case-variant near-duplicates that are genuinely
    distinct -- AR_YD_Shirting has 52 rows and AR_YD_SHIRTING has 2. Lowercasing
    to build the id collapsed them into one, so a frontend sending back the id
    it was given would silently select the other value.
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")


# Tokens that could name an entity. Underscores are kept because the business
# object types are underscore-delimited and users type them that way.
_CANDIDATE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")

# Words that look like candidate tokens but never name a business object.
_NOT_AN_ENTITY = frozenset(
    "show the and for with items item all any are how many what which "
    "give me my this that those these them list count total".split()
)


def _is_partial_name(token: str, value: str) -> bool:
    """Whether ``token`` is a run of whole components of ``value``.

    The names are built out of underscore-delimited parts, so a partial name
    has to break on those parts. Plain substring matching made "sales" a
    candidate prefix of AR_SALESPLAN_Suiting, and a clear question about the
    sales team was answered with "which sales type did you mean?" instead of
    being answered at all.
    """
    parts = [p.lower() for p in value.split("_")]
    needle = [p.lower() for p in token.split("_")]
    if not needle:
        return False
    return any(
        parts[i:i + len(needle)] == needle
        for i in range(len(parts) - len(needle) + 1)
    )


def clarify_entity(question: str, gazetteer: list[str]) -> FollowUp | None:
    """Ask which entity was meant, when a partial name matches several.

    "AR_YD" is not a business object type, but three of them begin with it.
    Guessing picks one at random; refusing to answer helps nobody. Naming the
    three is the only useful move, and it is only possible because the
    gazetteer is generated from the database.

    Returns None when the question names an entity outright, or names nothing
    resembling one -- neither is this kind of ambiguity.
    """
    from pipeline.context import detect_entity

    if detect_entity(question, gazetteer) is not None:
        return None  # unambiguous; nothing to ask

    for token in sorted(_CANDIDATE_TOKEN.findall(question), key=len, reverse=True):
        if token.lower() in _NOT_AN_ENTITY:
            continue
        matches = [v for v in gazetteer if _is_partial_name(token, v)]
        if len(matches) < 2:
            continue
        # A word that ends every name it matches is naming a family, not an
        # unfinished identifier. "Suiting" is the last component of all five
        # types that carry it and means all of them; "AR_YD" is the last
        # component of none of its matches, which is what makes it a name the
        # user stopped typing.
        if all(v.lower().endswith(token.lower()) for v in matches):
            continue
        return FollowUp(
            type="clarification",
            reason="ambiguous_entity",
            question=f"Which {token} type did you mean?",
            suggestions=[
                Suggestion(
                    id=f"set_entity_{_value_id(value)}",
                    label=value,
                    action=Action(type="set_entity",
                                  field="initiative_type",
                                  operator="=",
                                  value=value),
                )
                for value in sorted(matches)
            ],
        )
    return None


# ------------------------------------------------------------------ schema --

META_DIR = Path(__file__).resolve().parents[1] / "metadata"

# Columns worth sorting by, most interesting first. Name fragments rather than
# literal columns so this stays true for both tms_initiative_flat and
# tms_task_flat without listing either.
_SORTABLE = ("due", "delay", "elapsed", "remaining", "created")

# Never offered as a grouping: the entity column is what the user already
# chose, and free-text columns produce one group per row.
_NOT_GROUPABLE = frozenset({"initiative_type", "workflow_code", "workflow_name"})


@lru_cache(maxsize=1)
def _schema() -> dict:
    return yaml.safe_load(
        (META_DIR / "schema_description.yaml").read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def _rule_predicates() -> tuple[tuple[str, str, str, str], ...]:
    """Single-column predicates the business registry considers meaningful.

    Which filters are worth offering is a domain question, and the registry
    has already answered it -- "active", "open", "delayed" are named rules
    with SQL. Deriving the suggestions from that file instead of a list in
    this module means the two can never disagree, and adding a rule adds a
    suggestion for free.

    Returns (rule_name, table, column, value) for the rules that are a single
    equality. Multi-condition rules like my_tasks are skipped: they are not a
    filter a user can toggle.
    """
    doc = yaml.safe_load(
        (META_DIR / "business_rules.yaml").read_text(encoding="utf-8")) or {}
    out = []
    pattern = re.compile(r"^(\w+)\.(\w+)\s*=\s*'([^']*)'$")
    for rule in doc.get("rules") or []:
        fragment = (rule.get("sql_fragment") or "").strip()
        match = pattern.match(fragment)
        if match:
            out.append((rule["name"], *match.groups()))
    return tuple(out)


def _default_values() -> dict[str, str]:
    """Column -> the value the active-first default would have added.

    Read out of the registry rather than written here, so that renaming a
    status value in the rules cannot leave this list quietly wrong. The
    default_to_active policy rule carries no fragment of its own by design --
    it must not become a togglable filter -- so the values come from the two
    rules it refers to.
    """
    return {
        column: value
        for name, _table, column, value in _rule_predicates()
        if name in ("active_initiative", "open_task")
    }


def _enum_columns(table: str) -> dict[str, list[str]]:
    spec = (_schema().get("tables") or {}).get(table) or {}
    return {
        column: [str(v) for v in cspec["values"]]
        for column, cspec in (spec.get("columns") or {}).items()
        if isinstance(cspec, dict) and 2 <= len(cspec.get("values") or []) <= 12
    }


def _columns(table: str) -> dict:
    return ((_schema().get("tables") or {}).get(table) or {}).get("columns") or {}


# ------------------------------------------------------------- exploration --

def _varies(result: dict | None, column: str) -> bool | None:
    """Whether the returned rows hold more than one value for ``column``.

    None means "no information": there was no result, no rows, or the column
    was not projected. None is not False -- a suggestion must not be
    suppressed because the evidence is missing, only because the evidence is
    against it.
    """
    if not isinstance(result, dict):
        return None
    columns, rows = result.get("columns"), result.get("rows")
    if not columns or not rows or column not in columns:
        return None
    index = columns.index(column)
    seen = set()
    for row in rows:
        if index < len(row):
            seen.add(row[index])
        if len(seen) > 1:
            return True
    return False


def _projected(result: dict | None, column: str) -> bool | None:
    """Whether ``column`` is among the columns the answer actually carries."""
    if not isinstance(result, dict) or not result.get("columns"):
        return None
    return column in result["columns"]


def explore(state, row_count: int | None,
            result: dict | None = None) -> FollowUp | None:
    """Next moves worth offering, or None when there are none worth offering.

    Suggestions are only useful while they are specific, so this is gated
    rather than unconditional. An empty result has nothing to narrow, a query
    that never ran has no shape to build on, and one lone suggestion is not a
    choice -- in all three cases the honest answer is to say nothing.
    """
    if state is None or state.is_empty() or not state.active_tables:
        return None
    if row_count is not None and row_count <= 0:
        return None

    table = state.active_tables[0]
    in_force = set(state.active_filters)
    # A column the hierarchy does not show is not worth grouping or
    # sorting by either. That one declaration is what keeps
    # task_display_status out of a GROUP BY the schema explicitly
    # forbids, and boolean flags like is_delayed_open_task out of a sort.
    hidden = hidden_names(state.active_tables)
    # The predicates themselves, not just their columns: telling a
    # defaulted status from one the user chose means reading the value.
    in_force_predicates = dict(state.active_filters)
    suggestions: list[Suggestion] = []

    # A grouped answer's most obvious continuation is the rows behind it.
    if state.active_grouping:
        suggestions.append(Suggestion(
            id="drill_down_rows",
            label="Show the individual rows",
            action=Action(type="drill_down", field=state.active_grouping[0]),
        ))

    # Narrowing, taken from the registry's named rules -- but at most one per
    # column. The registry names three status rules, and offering all three
    # spent three of the four slots on one column and pushed out sorting and
    # counting. Registry order carries the salience: active before closed
    # before short closed, which is also the order people ask for them.
    offered_columns: set[str] = set()
    for name, rule_table, column, value in _rule_predicates():
        if rule_table != table or column in in_force or column in offered_columns:
            continue
        offered_columns.add(column)
        suggestions.append(Suggestion(
            id=f"filter_{_slug(name)}",
            label=f"Only the {value.lower()} ones",
            action=Action(type="add_filter", field=column,
                          operator="=", value=value),
        ))

    # Breaking the answer down, but only if it is not already broken down.
    if not state.active_grouping:
        for column in _enum_columns(table):
            if column in _NOT_GROUPABLE or column in in_force or column in hidden:
                continue
            # One group is not a breakdown. Only skip on evidence against:
            # _varies returns None when the column was not projected, and that
            # is not a reason to withhold the suggestion.
            if _varies(result, column) is False:
                continue
            suggestions.append(Suggestion(
                id=f"group_{_slug(column)}",
                label=f"Group by {column_phrase(column)}",
                action=Action(type="add_group_by", field=column),
            ))
            break

    # Ordering, once there is a list to order.
    if state.active_sorting is None and state.last_intent == "list":
        for fragment in _SORTABLE:
            column = next(
                (c for c in _columns(table)
                 if fragment in c and c not in hidden
                 and _projected(result, c) is not False),
                None)
            if column:
                suggestions.append(Suggestion(
                    id=f"sort_{_slug(column)}",
                    label=f"Sort by {column_phrase(column)}",
                    action=Action(type="set_sort", field=column, operator="DESC"),
                ))
                break

    # Letting go of a narrowing the user themselves added.
    # One narrowing is enough to be worth undoing -- "show all again" is a
    # next move in its own right. Requiring two left a single-filter count
    # with one suggestion, which is not a choice, so the layer said nothing.
    # The subject is still never offered: dropping that is a different
    # question, not a refinement of this one.
    removable = [c for c in in_force if c not in _NOT_GROUPABLE]
    if removable:
        column = sorted(removable)[0]
        # A status filter matching the active-first default was never typed by
        # the user, so "remove your filter" describes it from the system's
        # point of view. Dropping it is the only way out of the default, which
        # makes this label load-bearing: it has to read like the question a
        # person would actually ask. The action is unchanged -- remove_filter
        # on the status column is exactly right.
        defaulted = _default_values().get(column)
        was_defaulted = (
            defaulted is not None
            and f"'{defaulted}'" in (in_force_predicates.get(column) or "")
        )
        label = (
            f"Show every {column_phrase(column)}, not just {defaulted.lower()}"
            if was_defaulted
            else f"Remove the {column_phrase(column)} filter"
        )
        suggestions.append(Suggestion(
            id=f"remove_{_slug(column)}",
            label=label,
            action=Action(type="remove_filter", field=column),
        ))

    # Counting, when the answer was a list of things rather than a number.
    if state.last_intent == "list":
        suggestions.append(Suggestion(
            id="aggregate_count",
            label="Just count them",
            action=Action(type="set_aggregate", field="*", operator="COUNT"),
        ))

    if len(suggestions) < 2:
        return None

    # Four chips, and the escape hatch is built last, so it is the first thing
    # the cap drops -- while being the one suggestion the reader cannot
    # reconstruct for themselves. Every other chip here narrows an answer they
    # can already see; this is the only way back out of a filter the system
    # added and never mentioned. It is kept at the cost of the chip in front of
    # it, whatever that happens to be.
    chosen = suggestions[:4]
    escape = next(
        (s for s in suggestions if s.action.type == "remove_filter"), None)
    if escape is not None and escape not in chosen:
        chosen = chosen[:3] + [escape]

    return FollowUp(
        type="exploration",
        reason="useful_next_actions",
        question="What would you like to explore next?",
        suggestions=chosen,
    )


# ------------------------------------------------------- applying an action --

def apply_action(state, action: Action) -> str:
    """Fold a chosen suggestion into the state, and say what to ask next.

    Two things happen, and the split matters. The state changes immediately,
    so the context the model sees on the next turn already reflects what the
    user picked. The question is returned as ordinary text, so that turn goes
    through the same path as anything typed by hand.

    What deliberately does not happen is SQL generation. An action that
    carried its own SQL would be a second query builder, and the moment the
    two disagreed there would be no way to tell which was right. The state
    written here is provisional in exactly the way the rest of the pipeline
    expects: update_state overwrites it from whatever query actually ran.
    """
    label = column_phrase(action.field)

    if action.type in ("add_filter", "replace_filter"):
        operator = action.operator or "="
        state.active_filters[action.field] = f"{action.field} {operator} '{action.value}'"
        return f"Only the ones where {label} is {action.value}"

    if action.type == "remove_filter":
        state.active_filters.pop(action.field, None)
        return f"Remove the {label} filter"

    if action.type == "add_group_by":
        state.active_grouping = [action.field]
        return f"Group them by {label}"

    if action.type == "drill_down":
        state.active_grouping = []
        return "Show the individual rows instead of the totals"

    if action.type == "set_sort":
        direction = (action.operator or "DESC").upper()
        state.active_sorting = f"{action.field} {direction}"
        return f"Sort them by {label}, {'highest' if direction == 'DESC' else 'lowest'} first"

    if action.type == "set_limit":
        state.active_limit = int(action.value)
        return f"Just the first {action.value}"

    if action.type == "set_aggregate":
        state.active_grouping = []
        state.last_intent = "aggregate"
        return "How many are there?"

    if action.type == "set_entity":
        state.active_entity = action.value
        state.active_filters = {
            column: predicate
            for column, predicate in state.active_filters.items()
            if column != action.field
        }
        state.active_filters[action.field] = f"{action.field} = '{action.value}'"
        return f"{action.value}"

    raise ValueError(f"no mutation defined for action type {action.type!r}")


# --------------------------------------------------- structuring a clarify --

@lru_cache(maxsize=1)
def _enum_lookup() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every enumerated column in the schema, longest name first.

    Longest first so that "initiative_status" is recognised before the
    "status" inside it, which belongs to a different table.
    """
    found: dict[str, tuple[str, ...]] = {}
    for _, spec in (_schema().get("tables") or {}).items():
        for column, cspec in (spec.get("columns") or {}).items():
            if isinstance(cspec, dict) and cspec.get("values"):
                found.setdefault(column, tuple(str(v) for v in cspec["values"]))
    return tuple(sorted(found.items(), key=lambda kv: -len(kv[0])))


def _interpretation_token() -> str:
    """A nonce identifying one clarification's set of chips."""
    return secrets.token_hex(6)


def clarification_followup(text: str, model_options: list[str] | None = None,
                           about: str | None = None) -> FollowUp:
    """Turn the model's free-text clarification into the structured contract.

    The division of labour is deliberate. The model is good at noticing that a
    question cannot be answered and poor at reciting the values that would
    answer it; the schema is the reverse. So the model supplies the reason in
    prose, this function supplies the candidates, and nothing that reaches the
    user as a choice came from anywhere but the database.

    The prose is kept as the question because it explains the specific problem
    better than any template could.

    One exception, and it is narrow. When the ambiguity is about what the
    question MEANS rather than which value it names, the schema has nothing to
    offer: "performing poorly" could be overdue tasks, delayed tasks, open
    backlog or initiatives at risk, and no column enumerates those readings.
    Only the model can produce them, and it already does -- it numbers them in
    the prose. Discarding them and offering the values of whichever column the
    prose happened to mention is how a five-way question came back as "No /
    Yes". So model-supplied readings are taken when present.
    """
    # The readings are prose the model wrote, so they can name a table exactly
    # as a clarification can. Asked about a table that does not exist, it
    # helpfully offered the two that do -- as chips, which the boundary does
    # not scrub because a chip is normally a value rather than a sentence.
    #
    # Filtered here rather than at the boundary because only here is it known
    # where a chip came from. The enum and gazetteer chips below are built
    # from real data by this function, and must not be filtered: a genuine
    # initiative type like AR_YD_Suiting looks exactly like an identifier and
    # is exactly what the user needs offered.
    readings = [o for o in (model_options or [])
                if not names_a_database_object(o)]

    # Same cutoff as the enum path below, for the same reason.
    if readings and len(readings) <= 8:
        token = _interpretation_token()
        return FollowUp(
            type="clarification",
            reason="ambiguous_interpretation",
            question=" ".join(text.split()),
            suggestions=[
                Suggestion(id=f"interpretation_{i + 1}", label=option,
                           action=None, ref=f"{token}.{i + 1}")
                for i, option in enumerate(readings)
            ],
        )

    # `about` is the model saying which column the doubt is about, in a key of
    # its own. The scan of the question is kept behind it: a reply that omits
    # the key, and every reply written before the key existed, still finds its
    # column the old way. What changes is that a clean question no longer has
    # to go without chips -- which it did, because the scan could only match a
    # question that named the column out loud.
    named = (about or "").strip()
    for column, values in _enum_lookup():
        if column != named and column not in text:
            continue
        # Too many options stop being a choice and become a list to read.
        if len(values) > 8:
            break
        return FollowUp(
            type="clarification",
            reason="unknown_value",
            question=" ".join(text.split()),
            suggestions=[
                Suggestion(
                    id=f"filter_{_slug(column)}_{_value_id(value)}",
                    label=value,
                    action=Action(type="add_filter", field=column,
                                  operator="=", value=value),
                )
                for value in values
            ],
        )

    return FollowUp(
        type="clarification",
        reason="ambiguous_request",
        question=" ".join(text.split()),
        suggestions=[],
    )


# ------------------------------------------------------------ the decision --

NO_FOLLOWUP = FollowUp(type="none", reason="answer_complete", question="",
                       suggestions=[], allow_free_text=True)


def next_questions(state, row_count: int | None,
                   model_next: list[str] | None = None) -> FollowUp | None:
    """The model's follow-up questions, as chips.

    Same gates the registry path applies, for the same reasons: an empty result
    has nothing to explore, and one suggestion is not a choice.

    Each carries no action. Choosing one sends its text as an ordinary
    question, so a suggestion that turns out to name something absent is caught
    by the clarification path exactly as a typed question would be -- there is
    nothing here that can put a made-up value into a query.
    """
    if not model_next or len(model_next) < 2:
        return None
    if row_count is not None and row_count <= 0:
        return None
    token = _interpretation_token()
    return FollowUp(
        type="exploration",
        reason="useful_next_questions",
        question="What would you like to know next?",
        suggestions=[
            Suggestion(id=f"next_{i + 1}", label=question, action=None,
                       ref=f"{token}.{i + 1}")
            for i, question in enumerate(list(model_next)[:4])
        ],
    )


def decide(state, row_count: int | None, clarification: str | None,
           result: dict | None = None,
           model_options: list[str] | None = None,
           model_next: list[str] | None = None,
           clarify_about: str | None = None) -> FollowUp:
    """What to say once the turn is over.

    Ordered by how much the user needs it. An unanswered question needs a
    clarification more than an answered one needs suggestions, and an answer
    with no obvious continuation needs neither -- offering something anyway is
    how a helpful feature becomes noise.
    """
    if clarification is not None:
        return clarification_followup(clarification, model_options,
                                      clarify_about)
    # The model's own suggestions first, because only they can be about the
    # question. explore() reads the business-rule registry, which knows what
    # the schema affords and nothing about what was asked -- so after "which
    # departments are performing poorly" it offers "Just count them".
    #
    # Kept as the fallback rather than replaced: a reply that carries no
    # suggestions, and every reply written before this field existed, still
    # gets the registry's.
    suggested = next_questions(state, row_count, model_next)
    if suggested is not None:
        return suggested
    return explore(state, row_count, result) or NO_FOLLOWUP


# ------------------------------------------------ answering a clarification --

def resolve_clarification(
    answer: str,
    original_question: str,
    pending: FollowUp | None,
) -> str | None:
    """The original question with the user's choice filled in.

    Asking "which one?" is only worth doing if the answer can be understood.
    Without this, the reply to a clarification arrives as a bare noun with no
    context, and the model can only ask what to do with it -- so the thread
    deadlocks one turn after the clarification that was meant to unblock it.

    Resolution is a substitution rather than a new question, which is what
    makes the result read like something a person would have typed: "Show the
    AR_YD items" plus "AR_YD_Suiting" is "Show the AR_YD_Suiting items", and
    that goes through the ordinary path with nothing special about it.

    Returns None when the reply is not an answer. The user is entitled to
    ignore the question and ask something else, and treating that as a choice
    would be worse than having asked at all.
    """
    if pending is None or pending.type != "clarification" or not pending.suggestions:
        return None

    reply = " ".join(answer.split()).strip().strip("?.!")
    if not reply:
        return None

    # An id is a machine token and is matched exactly. Lowercasing it would
    # reintroduce the collision between AR_YD_Shirting and AR_YD_SHIRTING that
    # the id was made case-preserving to avoid.
    by_id = [_chosen_value(s) for s in pending.suggestions if s.id == reply]
    if len(by_id) == 1:
        chosen = by_id[0]
    else:
        # A person types the value, in whatever case they please -- unless
        # that is itself ambiguous, in which case the exact spelling decides.
        candidates = [
            _chosen_value(s) for s in pending.suggestions
            if _chosen_value(s)
            and reply.lower() in (_chosen_value(s).lower(), s.label.lower())
        ]
        if len(candidates) > 1:
            candidates = [v for v in candidates if v == reply]
        if len(candidates) != 1:
            # "4", when the model numbered four readings and the user picked
            # one. Before the substring pass, so a numeric value cannot be
            # resolved by the looser rule.
            ordinal = _ordinal_choice(reply, pending)
            if ordinal is not None:
                return _resume(original_question, ordinal)
        if len(candidates) != 1:
            # "the suiting one" -- named, but not on its own.
            candidates = [_chosen_value(s) for s in pending.suggestions
                          if _chosen_value(s)
                          and _chosen_value(s).lower() in reply.lower()]
        if len(candidates) != 1:
            return None
        chosen = candidates[0]

    return _resume(original_question, chosen)


def _chosen_value(suggestion: Suggestion) -> str | None:
    """What a suggestion resolves to when it is chosen.

    An action's value where there is one, and the label otherwise. A reading
    mutates no state, so it carries no action -- without the fallback every
    match pass would skip it and typing a reading out in full would fail to
    resolve just as surely as typing its number.
    """
    if suggestion.action is not None and suggestion.action.value:
        return suggestion.action.value
    return suggestion.label or None


def _ordinal_index(reply: str) -> int | None:
    """A reply read as a position in a list, 1-based, or None."""
    reply = (reply or "").strip()
    found = re.match(
        r"^(?:the\s+|option\s*|choice\s*|number\s*|no\.?\s*|#\s*)*(\d{1,2})"
        r"(?:st|nd|rd|th)?\s*[.)]?$",
        reply, re.IGNORECASE)
    if found:
        return int(found.group(1))
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
    found = re.match(r"^(?:the\s+)?([a-z]+)(?:\s+one)?$", reply, re.IGNORECASE)
    if found:
        return words.get(found.group(1).lower())
    return None


def _ordinal_choice(reply: str, pending: FollowUp) -> str | None:
    """The reading a positional reply picked, if it picked one.

    Only ever offered against readings the model itself numbered in prose. Two
    reasons, and both are load-bearing.

    Gazetteer candidates are not positionally answerable. The gazetteer is not
    deduplicated, so "Show the AR_YD items" offers five candidates of which two
    pairs are the same string -- asking someone to distinguish option 2 from
    option 3 when both read AR_YD_Shirting is not a question with an answer.

    And a bare number means nothing on its own. Asked to choose between listing
    and grouping, a user once replied "3" and the turn came back as LIMIT 3. A
    number is a choice only where a numbered list was offered, which is
    precisely what this gate tests.
    """
    if pending.reason != "ambiguous_interpretation":
        return None
    index = _ordinal_index(reply)
    if index is None or index < 1 or index > len(pending.suggestions):
        # Out of range is not a near miss. Nine, against four readings, is the
        # user talking about something else.
        return None
    return _chosen_value(pending.suggestions[index - 1])


def _resume(original_question: str, chosen: str) -> str:
    """The original question with the choice written into it.

    Substituting where the truncated name was is what makes the result read
    like something a person would have typed. When nothing in the question was
    a partial form of the choice -- which is always so for a reading, since a
    reading is a sentence rather than a name -- the choice is appended instead.
    """
    for token in sorted(_CANDIDATE_TOKEN.findall(original_question),
                        key=len, reverse=True):
        if token.lower() in _NOT_AN_ENTITY or token == chosen:
            continue
        if _is_partial_name(token, chosen):
            return original_question.replace(token, chosen)
    return f"{original_question} ({chosen})"


def label_for_ref(pending: FollowUp | None, ref: str) -> str | None:
    """The reading a chip was offered for, given the ref it carries.

    Matching against the clarification currently outstanding is what ties a
    click to the question that prompted it: a chip still on screen from three
    turns further up carries a nonce nothing is waiting on any more, so it
    matches nothing and its label is read as ordinary text instead of silently
    answering a question that has already moved on.
    """
    ref = (ref or "").strip()
    if not ref or pending is None or not pending.suggestions:
        return None
    for suggestion in pending.suggestions:
        if suggestion.ref == ref:
            return suggestion.label
    return None
