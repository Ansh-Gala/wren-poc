"""Repair layer: what the user typed versus what they meant.

Every correction here has to be justified by the schema. A repair layer that
guesses from a general English dictionary would happily turn a real column
name into a common word, so the vocabulary is built from the database's own
tables, columns and enum values and nothing else.
"""

from __future__ import annotations

from benchmark.normalize import normalize


def test_corrects_a_typo_against_schema_vocabulary():
    n = normalize("give me my actie task")
    assert n.question == "give me my active task"


def test_leaves_every_existing_benchmark_question_untouched():
    """The repair layer must be invisible when there is nothing to repair.

    Parametrised over the real suites rather than invented strings: these are
    the exact questions the benchmark asks, so a repair that mangles ordinary
    English shows up here instead of as an unexplained accuracy drop.
    """
    from pathlib import Path

    import yaml

    suites = [
        "benchmark/lean_questions.yaml",
        "benchmark/targeted_questions.yaml",
        "benchmark/expansion_questions.yaml",
    ]
    questions: list[str] = []
    for suite in suites:
        doc = yaml.safe_load(Path(suite).read_text(encoding="utf-8")) or {}
        for raw in doc.get("questions", []) or []:
            for turn in raw.get("turns", [raw]):
                if "question" in turn:
                    questions.append(" ".join(turn["question"].split()))

    assert len(questions) > 200, "suites did not load"

    # Pinned rather than forbidden outright. A spelling variant of a real
    # column value is a correct repair and should keep working; anything else
    # is the layer overreaching, and the two must not be confused. Early
    # versions turned "Sort by due date" into "short by due date" and "Back to
    # the first ones" into "black to the first ones" -- both would have shown
    # up here as an unlisted pair.
    allowed = {("colour", "color")}

    unexpected = []
    for question in questions:
        for repair in normalize(question).repairs:
            pair = (repair.original.lower(), repair.corrected.lower())
            if pair not in allowed:
                unexpected.append((question, pair))

    assert not unexpected, "repair layer rewrote correct questions:\n" + "\n".join(
        f"  {q!r}: {a!r} -> {b!r}" for q, (a, b) in unexpected[:20]
    )


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
