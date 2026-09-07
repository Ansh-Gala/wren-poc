"""Repair layer against the real question corpus.

Separate from tests/test_normalize.py, which tests the layer's rules on
invented strings and ships with pipeline/normalize.py. This file needs the
benchmark suites to exist, so it stays on develop: the assertion is about a
corpus, not about the module.
"""

from __future__ import annotations

from pipeline.normalize import normalize


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
