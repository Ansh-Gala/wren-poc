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

    # Both numbers for every word, so "task" and "tasks", "attribute" and
    # "attributes" are each known outright rather than one being reachable
    # from the other by adding a letter. Reachability was the bug: it let
    # "busines" pass as known because "business" is.
    both: set[str] = set(words)
    for word in words:
        both.add(word + ("es" if word.endswith(("s", "x", "ch", "sh")) else "s"))
        # "business" -> "busines" and "status" -> "statu" are not words, and
        # putting them in the vocabulary would readmit exactly the typos this
        # is meant to catch.
        if word.endswith(("ss", "us", "is")):
            continue
        if word.endswith("ies") and len(word) > 4:
            both.add(word[:-3] + "y")
        elif word.endswith("s") and len(word) > 3:
            # Strip only the "s". Taking "es" off "attributes" gives
            # "attribut", so the real singular stayed unknown and the correctly
            # spelled word "attribute" was "repaired" into the plural.
            both.add(word[:-1])
    return frozenset(both)


def _morphs(token: str) -> list[str]:
    """The token and its obvious singular/plural variants.

    The vocabulary is built from column names, which are inconsistent about
    number -- ``business_object_type`` is singular, ``open_tasks_list`` is
    plural. Without this, "items" is one edit from the known word "item" and
    gets "repaired" into it, silently rewriting half the benchmark.

    Suffixes are only ever stripped, never added. Adding a trailing "s" as
    evidence of knownness meant "busines" counted as known because
    "business" is -- so a typo one letter short of a real plural sailed
    through while far worse ones were repaired. The plural forms are put into
    the vocabulary instead, where they cannot launder a misspelling.
    """
    forms = [token]
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


def _edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Damerau-Levenshtein distance, giving up once past ``limit``.

    Transposition has to count as one edit rather than two, because swapping
    two adjacent letters is the commonest typo there is and two edits is far
    too loose a threshold to allow generally.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            current[j] = min(
                previous[j] + 1,            # deletion
                current[j - 1] + 1,         # insertion
                previous[j - 1] + (ca != cb),  # substitution
            )
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                current[j] = min(current[j], previous_previous[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        previous_previous, previous = previous, current
    return previous[len(b)]


def _best_match(token: str, vocabulary: frozenset[str]) -> str | None:
    """The single closest vocabulary term, or None if there isn't one.

    Two ways to qualify, because neither alone is enough. The similarity ratio
    catches misspellings that keep a word's overall shape; a single edit
    catches the transpositions that ratio scores at exactly 0.80, just under
    any threshold loose enough to be safe.

    Ranked by edit distance first so that "objets" resolves to "objects" (one
    dropped letter) rather than "object" (two).
    """
    scored = []
    for term in vocabulary:
        if abs(len(term) - len(token)) > 3:
            continue
        distance = _edit_distance(token, term)
        ratio = SequenceMatcher(None, token, term).ratio()
        near = distance <= 1 and len(token) >= 5
        if near or ratio >= _THRESHOLD:
            scored.append((distance, -ratio, term))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


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


# A single quote only opens a quotation when it does not follow a letter --
# otherwise the apostrophes in "don't" and "user's" would open spans and
# silently disable repair for the rest of the question.
_QUOTED = re.compile(r'"[^"]*"' + r"|(?<![A-Za-z])'[^']*'")


def _quoted_spans(question: str) -> list[tuple[int, int]]:
    """Character ranges the user put in quotes.

    Quoting is how someone says "this is a literal value, not my spelling".
    """
    return [m.span() for m in _QUOTED.finditer(question)]


def _starts_a_sentence(question: str, start: int) -> bool:
    """Whether the token at ``start`` opens the question or a new sentence.

    Sentences are capitalised regardless of what their first word is, so a
    capital there says nothing about the word. A capital anywhere else does.
    """
    i = start - 1
    while i >= 0 and question[i].isspace():
        i -= 1
    return i < 0 or question[i] in ".?!"


def normalize(question: str) -> Normalized:
    """Rewrite obvious misspellings of schema terms, leaving everything else."""
    vocabulary = load_vocabulary()
    repairs: list[Repair] = []
    quoted = _quoted_spans(question)

    def repair_token(match: re.Match) -> str:
        token = match.group(0)
        lowered = token.lower()
        if len(lowered) < _MIN_LENGTH or lowered in _QUERY_WORDS:
            return token

        # Inside quotes the user is naming a value. Repairing there is a guess
        # about their data rather than about their spelling, and an empty
        # result is at least visible where a rewritten filter is not.
        start = match.start()
        if any(lo < start < hi for lo, hi in quoted):
            return token

        # A capital mid-sentence marks a name. This is the only thing that
        # separates a name from a typo here: "Generation" and "penetration"
        # score 0.857 on ratio and 2 on edit distance, which is exactly what
        # the genuine typo "delyaed"/"delayed" scores, so no threshold can
        # tell them apart. Real session: "UID Generation" is a task name on 58
        # rows and became ILIKE '%UID Penetration%', which matches nothing.
        if token[:1].isupper() and not _starts_a_sentence(question, start):
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
