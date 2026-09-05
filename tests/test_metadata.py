import pathlib

import pytest
import yaml

from benchmark.questions import load_questions
from database.connection import run_readonly

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_COLUMNS = {
    "users": {"id", "full_name", "email", "department", "role", "status"},
    "workflows": {"id", "name", "description", "category", "status",
                  "owner_user_id", "created_at", "updated_at"},
    "tasks": {"id", "workflow_id", "name", "description", "status", "priority",
              "assigned_user_id", "due_date", "completed_at", "created_at"},
}


def _load(name):
    return yaml.safe_load((ROOT / "metadata" / name).read_text(encoding="utf-8"))


def test_every_column_is_described():
    desc = _load("schema_description.yaml")
    for table, cols in EXPECTED_COLUMNS.items():
        documented = set(desc["tables"][table]["columns"])
        assert documented == cols, f"{table}: mismatch {cols ^ documented}"


def test_descriptions_are_not_trivial_restatements():
    """A description that just repeats the column name teaches a model nothing."""
    desc = _load("schema_description.yaml")
    for table, tdef in desc["tables"].items():
        for col, cdef in tdef["columns"].items():
            text = " ".join(cdef["description"].split())
            assert len(text) > 40, f"{table}.{col} description is too thin: {text!r}"
            assert text.lower() != f"{col.replace('_', ' ')} of the {table[:-1]}"


def test_enum_columns_document_every_value():
    desc = _load("schema_description.yaml")
    cases = [
        ("users", "status", ["ACTIVE", "INACTIVE"]),
        ("users", "role", ["MANAGER", "MEMBER", "VIEWER"]),
        ("tasks", "status", ["TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED"]),
        ("tasks", "priority", ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
        ("workflows", "status", ["ACTIVE", "DRAFT", "ARCHIVED"]),
    ]
    for table, column, values in cases:
        text = desc["tables"][table]["columns"][column]["description"]
        for value in values:
            assert value in text, f"{table}.{column} does not document {value}"


def test_owner_versus_assignee_is_called_out_explicitly():
    """The schema's main trap must be documented, or config B/C teach nothing."""
    desc = _load("schema_description.yaml")
    owner = desc["tables"]["workflows"]["columns"]["owner_user_id"]["description"]
    assignee = desc["tables"]["tasks"]["columns"]["assigned_user_id"]["description"]
    assert "assigned_user_id" in owner
    assert "owner_user_id" in assignee
    subjects = " ".join(a["subject"] for a in desc["ambiguities"])
    assert "owner" in subjects and "assignee" in subjects


def test_business_rules_have_definition_and_sql():
    rules = _load("business_rules.yaml")["rules"]
    assert len(rules) >= 15
    names = [r["name"] for r in rules]
    assert len(names) == len(set(names)), "duplicate rule names"
    for rule in rules:
        assert rule["definition"].strip()
        assert rule["sql_fragment"].strip()


def test_key_business_rules_are_present():
    names = {r["name"] for r in _load("business_rules.yaml")["rules"]}
    for required in (
        "active_user", "completed_task", "open_task", "overdue_task",
        "workflow_owner_join", "task_assignee_join", "count_tasks",
        "count_workflows_after_join", "never_confuse_owner_with_assignee",
        "high_priority",
    ):
        assert required in names, f"missing rule: {required}"


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
