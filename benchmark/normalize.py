"""Repair what the user typed into what the schema calls it.

"give me my actie task" is not a hard question, but it reaches the model as a
word the schema has never heard of, and the model's only options are to guess
or to ask. Neither is what the user wanted: there is exactly one schema term
within one keystroke of "actie", so the system can simply fix it.

The vocabulary is built from the database's own tables, columns and enum
values. That constraint is the whole design. A repair layer backed by a
general English dictionary would cheerfully rewrite a real column name into a
common word; one backed by the schema can only ever move a token *towards*
something the database actually contains.

No LLM call. A spelling correction against a closed vocabulary is a string
comparison, and paying a model round-trip for it would cost more than the
ambiguity it resolves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import yaml

META_DIR = Path(__file__).resolve().parents[1] / "metadata"

# Below this many characters a typo is indistinguishable from a different
# word: "ope" is one edit from "open", "one" and "top".
_MIN_LENGTH = 4

# How close a token must be to a vocabulary term before it is treated as a
# misspelling of it. 0.82 accepts one transposition or dropped letter in a
# six-letter word ("actie"/"active" is 0.91, "delyaed"/"delayed" is 0.86) and
# rejects genuinely different words ("closed"/"closer" is 0.83 -- which is why
# both are in the vocabulary and neither is ever rewritten).
_THRESHOLD = 0.82

# The words people use to *ask* rather than to name. None of them is ever a
# reference to the data, so none is ever repaired -- and each of these is
# genuinely close to something in the schema: "sort" to "short", "back" to
# "black", "count" to "county". Left unguarded the layer turns "Sort by due
# date" into "short by due date", which is worse than any typo it fixes.
#
# This is a closed list on purpose. It is the vocabulary of the interface, not
# an English dictionary, and it only ever needs to grow when a new phrasing
# collides with a schema term.
_QUERY_WORDS = frozenset("""
show give list tell find get display want need like please thanks
only just also more less fewer few than that this these those them they their
there then other another same both all any some each every none
and but not with without for from into over under above below
between before after during while since until back again still ever never
now next last first second third top bottom most least many much
high higher highest low lower lowest large small big old older oldest
new newer newest recent recently
sort order group filter remove drop add include exclude expand narrow
change switch compare break down detail details drill
what which who whom whose when where how why
are were was been being have has had does did doing
can could will would shall should may might must
about per versus mine yours ours everything something anything nothing
overdue urgent pending done outstanding
""".split())


@dataclass(frozen=True)
class Repair:
    """One token rewritten, and why."""

    original: str
    corrected: str
    kind: str  # typo | abbreviation


@dataclass
class Normalized:
    question: str
    repairs: list[Repair] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


@lru_cache(maxsize=1)
def load_vocabulary() -> frozenset[str]:
    """Every word the database itself uses, lowercased.

    Table names, column names and enum values, each also split on underscores
    so that ``business_object_status`` contributes "business", "object" and
    "status" -- the words a person actually types.
    """
    doc = yaml.safe_load((META_DIR / "schema_description.yaml").read_text(encoding="utf-8")) or {}
    words: set[str] = set()

    def add(text: str) -> None:
        for part in re.split(r"[^A-Za-z]+", str(text)):
            if len(part) >= 3:
                words.add(part.lower())

    for table, spec in (doc.get("tables") or {}).items():
        add(table)
        for column, cspec in (spec.get("columns") or {}).items():
            add(column)
            if isinstance(cspec, dict):
                for value in cspec.get("values") or []:
                    add(value)

    return frozenset(words)


def _morphs(token: str) -> list[str]:
    """The token and its obvious singular/plural variants.

    The vocabulary is built from column names, which are inconsistent about
    number -- ``business_object_type`` is singular, ``open_tasks_list`` is
    plural. Without this, "items" is one edit from the known word "item" and
    gets "repaired" into it, silently rewriting half the benchmark.
    """
    forms = [token, token + "s"]
    for suffix, replacement in (
        ("ies", "y"), ("es", ""), ("s", ""),
        # "reopened" and "reopening" are ordinary inflections of the column
        # word "reopen"; without these they read as unknown tokens one edit
        # from it and get flattened back to the stem.
        ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"), ("er", ""),
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            forms.append(token[: -len(suffix)] + replacement)
    return forms


def _is_known(token: str, vocabulary: frozenset[str]) -> bool:
    return any(form in vocabulary for form in _morphs(token))


def _best_match(token: str, vocabulary: frozenset[str]) -> str | None:
    """The single closest vocabulary term, or None if there isn't one."""
    scored = [
        (SequenceMatcher(None, token, term).ratio(), term)
        for term in vocabulary
        if abs(len(term) - len(token)) <= 3
    ]
    scored = [(score, term) for score, term in scored if score >= _THRESHOLD]
    if not scored:
        return None
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored[0][1]


def _match_case(original: str, corrected: str) -> str:
    """Give the correction the shape the user typed.

    The vocabulary is lowercased, so a naive substitution turns a
    sentence-initial "Actie" into "active" mid-sentence. That is a second,
    quieter defect introduced by fixing the first one.
    """
    if original.isupper() and len(original) > 1:
        return corrected.upper()
    if original[:1].isupper():
        return corrected[:1].upper() + corrected[1:]
    return corrected


def normalize(question: str) -> Normalized:
    """Rewrite obvious misspellings of schema terms, leaving everything else."""
    vocabulary = load_vocabulary()
    repairs: list[Repair] = []

    def repair_token(match: re.Match) -> str:
        token = match.group(0)
        lowered = token.lower()
        if len(lowered) < _MIN_LENGTH or lowered in _QUERY_WORDS:
            return token
        if _is_known(lowered, vocabulary):
            return token
        corrected = _best_match(lowered, vocabulary)
        if corrected is None or corrected == lowered:
            return token
        corrected = _match_case(token, corrected)
        repairs.append(Repair(original=token, corrected=corrected, kind="typo"))
        return corrected

    rewritten = re.sub(r"[A-Za-z]+", repair_token, question)
    return Normalized(question=rewritten, repairs=repairs)
