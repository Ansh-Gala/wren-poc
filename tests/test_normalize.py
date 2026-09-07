"""Repair layer: what the user typed versus what they meant.

Every correction here has to be justified by the schema. A repair layer that
guesses from a general English dictionary would happily turn a real column
name into a common word, so the vocabulary is built from the database's own
tables, columns and enum values and nothing else.
"""

from __future__ import annotations

from pipeline.normalize import normalize


def test_corrects_a_typo_against_schema_vocabulary():
    n = normalize("give me my actie task")
    assert n.question == "give me my active task"


def test_repairs_a_single_transposed_or_dropped_letter():
    """The commonest typo of all, and a similarity ratio just misses it.

    "itmes" and "items" score 0.80 against a 0.82 threshold, as do "tsaks",
    "usres" and "colur" -- every one a single adjacent transposition or one
    dropped letter. Raising the ratio far enough to catch them would also
    start rewriting genuinely different words, so distance is measured
    directly instead.
    """
    for typed, meant in [
        ("show the AR_YD_Suiting itmes", "items"),
        ("show open tsaks", "tasks"),
        ("how many usres are there", "users"),
        ("show items by colur", "color"),
        ("how many objets are active", "objects"),
    ]:
        result = normalize(typed)
        assert meant in result.question, f"{typed!r} -> {result.question!r}"


def test_a_typo_is_not_hidden_by_being_one_letter_from_a_plural():
    """"busines" is not a word, but "busines" + "s" is, and that was enough.

    The morphology check added a trailing "s" as evidence a token was already
    known, so a typo one letter short of a real plural was passed through
    untouched while far worse typos were repaired.
    """
    assert normalize("filter by busines unit").question == "filter by business unit"


def test_a_capitalised_name_is_not_repaired_into_a_schema_word():
    """A word the user capitalised is a name, not a misspelling.

    Recovered from a real session. "UID Generation" is a task_display_name on
    58 rows; "penetration" is a schema word, from buff_penetration_days. The
    two score 0.857 on the similarity ratio and 2 on edit distance -- exactly
    what "delyaed"/"delayed" scores -- so neither threshold can separate them.
    What separates them is that the user wrote a capital G mid-sentence, which
    people do for names and not for typos.

    Left unfixed, the query went out as ILIKE '%UID Penetration%' and returned
    nothing, with the console reporting a confident zero rows.
    """
    for question in (
        "give me task closed just before UID Generation",
        # The user's complaint about the rewrite must survive it too: this one
        # contains "Penetration" because they typed it, so the check is that
        # "Generation" is still there afterwards, not that the other word is
        # absent.
        "why are you searching for Penetration i said UID Generation",
        "show me the UID Generation tasks",
    ):
        n = normalize(question)
        assert "Generation" in n.question, f"{question!r} -> {n.question!r}"
        assert not any(r.original == "Generation" for r in n.repairs)


def test_a_quoted_phrase_is_left_alone():
    """Quoting is how a user says "this is a literal value"."""
    for question in (
        'give me task closed just before "UID Generation"',
        "give me task closed just before 'UID Generation'",
    ):
        n = normalize(question)
        assert "Penetration" not in n.question, f"{question!r} -> {n.question!r}"


def test_a_quoted_typo_is_also_left_alone():
    """The same rule, applied where it costs something.

    Inside quotes the user is naming a value, so a repair there is a guess
    about their data rather than about their spelling. Not repairing is the
    conservative choice: an empty result is visible, a silently rewritten
    filter is not.
    """
    n = normalize('show me the "actie" ones')
    assert n.question == 'show me the "actie" ones'
    assert n.repairs == []


def test_a_sentence_initial_capital_is_still_repaired():
    """The capital rule must not swallow the first word of a question.

    "Actie" opening a sentence is capitalised only because sentences are, so
    it carries no signal about being a name.
    """
    n = normalize("Actie tasks please")
    assert n.question.startswith("Active")


def test_lowercase_typos_are_still_repaired_after_the_capital_rule():
    """Regression guard: the fix must only ever remove repairs, never add."""
    assert normalize("give me my actie task").question == "give me my active task"
    assert normalize("show the AR_YD_Suiting itmes").question.endswith("items")
