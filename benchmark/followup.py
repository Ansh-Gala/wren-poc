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
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

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
    action: Action

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "action": self.action.to_dict()}


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

    business_object_type holds case-variant near-duplicates that are genuinely
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
    from benchmark.context import detect_entity

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
                                  field="business_object_type",
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
# literal columns so this stays true for both tms_business_object_flat and
# tms_task_flat without listing either.
_SORTABLE = ("due", "delay", "elapsed", "remaining", "created")

# Never offered as a grouping: the entity column is what the user already
# chose, and free-text columns produce one group per row.
_NOT_GROUPABLE = frozenset({"business_object_type", "workflow_code", "workflow_name"})


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

def explore(state, row_count: int | None) -> FollowUp | None:
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
            if column in _NOT_GROUPABLE or column in in_force:
                continue
            suggestions.append(Suggestion(
                id=f"group_{_slug(column)}",
                label=f"Group by {column.replace('_', ' ')}",
                action=Action(type="add_group_by", field=column),
            ))
            break

    # Ordering, once there is a list to order.
    if state.active_sorting is None and state.last_intent == "list":
        for fragment in _SORTABLE:
            column = next((c for c in _columns(table) if fragment in c), None)
            if column:
                suggestions.append(Suggestion(
                    id=f"sort_{_slug(column)}",
                    label=f"Sort by {column.replace('_', ' ')}",
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
        suggestions.append(Suggestion(
            id=f"remove_{_slug(column)}",
            label=f"Remove the {column.replace('_', ' ')} filter",
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
    return FollowUp(
        type="exploration",
        reason="useful_next_actions",
        question="What would you like to explore next?",
        suggestions=suggestions[:4],
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
    label = (action.field or "").replace("_", " ")

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

    Longest first so that "business_object_status" is recognised before the
    "status" inside it, which belongs to a different table.
    """
    found: dict[str, tuple[str, ...]] = {}
    for _, spec in (_schema().get("tables") or {}).items():
        for column, cspec in (spec.get("columns") or {}).items():
            if isinstance(cspec, dict) and cspec.get("values"):
                found.setdefault(column, tuple(str(v) for v in cspec["values"]))
    return tuple(sorted(found.items(), key=lambda kv: -len(kv[0])))


def clarification_followup(text: str) -> FollowUp:
    """Turn the model's free-text clarification into the structured contract.

    The division of labour is deliberate. The model is good at noticing that a
    question cannot be answered and poor at reciting the values that would
    answer it; the schema is the reverse. So the model supplies the reason in
    prose, this function supplies the candidates, and nothing that reaches the
    user as a choice came from anywhere but the database.

    The prose is kept as the question because it explains the specific problem
    better than any template could.
    """
    for column, values in _enum_lookup():
        if column not in text:
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


def decide(state, row_count: int | None, clarification: str | None) -> FollowUp:
    """What to say once the turn is over.

    Ordered by how much the user needs it. An unanswered question needs a
    clarification more than an answered one needs suggestions, and an answer
    with no obvious continuation needs neither -- offering something anyway is
    how a helpful feature becomes noise.
    """
    if clarification is not None:
        return clarification_followup(clarification)
    return explore(state, row_count) or NO_FOLLOWUP


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
    by_id = [s.action.value for s in pending.suggestions if s.id == reply]
    if len(by_id) == 1:
        chosen = by_id[0]
    else:
        # A person types the value, in whatever case they please -- unless
        # that is itself ambiguous, in which case the exact spelling decides.
        candidates = [
            s.action.value for s in pending.suggestions
            if s.action.value
            and reply.lower() in (s.action.value.lower(), s.label.lower())
        ]
        if len(candidates) > 1:
            candidates = [v for v in candidates if v == reply]
        if len(candidates) != 1:
            # "the suiting one" -- named, but not on its own.
            candidates = [s.action.value for s in pending.suggestions
                          if s.action.value
                          and s.action.value.lower() in reply.lower()]
        if len(candidates) != 1:
            return None
        chosen = candidates[0]

    # Put the choice where the truncated name was, so the resumed question is
    # the one the user meant to ask in the first place.
    for token in sorted(_CANDIDATE_TOKEN.findall(original_question),
                        key=len, reverse=True):
        if token.lower() in _NOT_AN_ENTITY or token == chosen:
            continue
        if _is_partial_name(token, chosen):
            return original_question.replace(token, chosen)
    return f"{original_question} ({chosen})"
