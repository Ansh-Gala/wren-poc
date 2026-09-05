"""Load and select benchmark questions."""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

import yaml

from benchmark.models import Question

QUESTIONS_FILE = Path(__file__).resolve().parent / "questions.yaml"

# Fixed, so the A/B/C subset is the same set of questions every time and
# cross-configuration comparisons stay meaningful.
SUBSET_SEED = 20260904


def load_questions(path: Path | None = None) -> list[Question]:
    doc = yaml.safe_load((path or QUESTIONS_FILE).read_text(encoding="utf-8"))
    return [
        Question(
            id=q["id"],
            category=q["category"],
            question=" ".join(q["question"].split()),
            expected_sql=q["expected_sql"].strip(),
            ordered=bool(q.get("ordered", False)),
            tags=list(q.get("tags", []) or []),
            interpretation=q.get("interpretation"),
        )
        for q in doc["questions"]
    ]


def stratified_subset(questions: list[Question], size: int) -> list[Question]:
    """A reproducible sample that keeps every category represented.

    Used for the A/B/C knowledge-lift comparison, where running all questions
    against all configurations costs far more than the extra precision is
    worth. One question per category first, then fill by round-robin so the
    spread stays even.
    """
    if size >= len(questions):
        return list(questions)

    by_category: dict[str, list[Question]] = defaultdict(list)
    for q in questions:
        by_category[q.category].append(q)

    rng = random.Random(SUBSET_SEED)
    pools = {c: rng.sample(qs, len(qs)) for c, qs in by_category.items()}

    chosen: list[Question] = []
    categories = sorted(pools)
    while len(chosen) < size:
        progressed = False
        for category in categories:
            if pools[category]:
                chosen.append(pools[category].pop())
                progressed = True
                if len(chosen) == size:
                    break
        if not progressed:
            break

    order = {q.id: i for i, q in enumerate(questions)}
    return sorted(chosen, key=lambda q: order[q.id])


def select(
    questions: list[Question],
    categories: str | None = None,
    subset: int | None = None,
    ids: list[str] | None = None,
) -> list[Question]:
    selected = questions
    if ids:
        wanted = {i.upper() for i in ids}
        selected = [q for q in selected if q.id.upper() in wanted]
    if categories:
        wanted = {c.strip().upper() for c in categories.split(",") if c.strip()}
        selected = [q for q in selected if q.category.upper() in wanted]
    if subset:
        selected = stratified_subset(selected, subset)
    return selected
