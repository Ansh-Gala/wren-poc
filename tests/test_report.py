import csv
import json

from benchmark.models import QuestionResult
from benchmark.report import summarize, write_reports


def make(qid, cat, gen, exe, match, failure=None, tools=()):
    return QuestionResult(
        question_id=qid, category=cat, question="q",
        expected_sql="SELECT 1", generated_sql="SELECT 1" if gen else None,
        sql_valid=gen, execution_success=exe, result_match=match,
        parse_strategy="json" if gen else "none", tools_used=list(tools), tags=[],
        claude_time_ms=1000.0, sql_execution_time_ms=5.0, total_time_ms=1010.0,
        error=None, sqlstate=None, timed_out=False, cli_ok=True,
        failure_category=failure, config_name="D", privacy_mode="strict",
    )


RESULTS = [
    make("A01", "A", True, True, True, tools=["mcp__wren__get_mdl"]),
    make("A02", "A", True, True, False, failure="RESULT_MISMATCH"),
    make("B01", "B", True, False, False, failure="WRONG_COLUMN"),
    make("B02", "B", False, False, False, failure="PARSER_FAILURE"),
]


def test_summary_counts_are_computed_not_fabricated():
    s = summarize(RESULTS)
    assert s["total"] == 4
    assert s["sql_generated"] == 3
    assert s["sql_executable"] == 2
    assert s["result_match"] == 1
    assert round(s["result_accuracy_pct"], 2) == 25.00
    assert round(s["sql_generation_pct"], 2) == 75.00
    assert round(s["execution_success_pct"], 2) == 50.00


def test_per_category_breakdown():
    s = summarize(RESULTS)
    assert s["by_category"]["A"]["total"] == 2
    assert s["by_category"]["A"]["result_match"] == 1
    assert s["by_category"]["A"]["result_accuracy_pct"] == 50.0
    assert s["by_category"]["B"]["result_match"] == 0


def test_failure_histogram_and_heuristic_count():
    s = summarize(RESULTS)
    assert s["failure_categories"]["RESULT_MISMATCH"] == 1
    assert s["failure_categories"]["WRONG_COLUMN"] == 1
    # RESULT_MISMATCH is heuristic; WRONG_COLUMN and PARSER_FAILURE are not.
    assert s["heuristic_failure_count"] == 1


def test_tool_usage_is_counted():
    assert summarize(RESULTS)["tools_used"]["mcp__wren__get_mdl"] == 1


def test_writes_all_three_report_files(tmp_path):
    write_reports(RESULTS, tmp_path)

    payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 4
    assert len(payload["results"]) == 4

    rows = list(csv.DictReader((tmp_path / "latest.csv").open(encoding="utf-8")))
    assert len(rows) == 4
    assert rows[0]["question_id"] == "A01"

    md = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "RESULT ACCURACY" in md.upper()
    assert "25.00%" in md


def test_markdown_reports_failures_and_flags_heuristics(tmp_path):
    write_reports(RESULTS, tmp_path)
    md = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "A02" in md and "RESULT_MISMATCH" in md
    assert "heuristic" in md.lower()
    assert "run-to-run variance" in md


def test_markdown_states_that_rows_never_reached_claude(tmp_path):
    write_reports(RESULTS, tmp_path)
    md = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "No database rows were sent to Claude" in md


def test_summary_of_empty_run_does_not_divide_by_zero():
    s = summarize([])
    assert s["total"] == 0
    assert s["result_accuracy_pct"] == 0.0
    assert s["by_category"] == {}


def test_all_passing_run_reports_full_accuracy():
    s = summarize([make("A01", "A", True, True, True)])
    assert s["result_accuracy_pct"] == 100.0
    assert s["failure_categories"] == {}
