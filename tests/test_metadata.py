import pathlib

import pytest
import yaml

from benchmark.questions import load_questions
from database.connection import run_readonly

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    return yaml.safe_load((ROOT / "metadata" / name).read_text(encoding="utf-8"))


def test_exemplar_pairs_use_wren_native_format():
    doc = _load("question_sql_pairs.yaml")
    assert doc["version"] == 1
    for i, pair in enumerate(doc["pairs"], 1):
        assert "nl" in pair and "sql" in pair, f"pair #{i} missing nl/sql"
        assert isinstance(pair["nl"], str) and isinstance(pair["sql"], str)


def test_exemplars_are_disjoint_from_benchmark_questions():
    """Otherwise configuration D measures memorisation, not generalisation."""
    pairs = {" ".join(p["nl"].split()).lower().rstrip(".")
             for p in _load("question_sql_pairs.yaml")["pairs"]}
    bench = {" ".join(q.question.split()).lower().rstrip(".")
             for q in load_questions()}
    overlap = pairs & bench
    assert not overlap, f"exemplar leaked into benchmark: {overlap}"


@pytest.mark.integration
def test_every_exemplar_sql_executes(settings):
    failures = []
    for pair in _load("question_sql_pairs.yaml")["pairs"]:
        result = run_readonly(settings, pair["sql"], 15000)
        if result.error:
            failures.append((pair["nl"], result.error.splitlines()[0]))
    assert not failures, failures
