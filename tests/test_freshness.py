"""Which queries carry the "not live" note.

The cases are the Drupal port's tests/freshness/check.php, one for one, so the
two implementations are held to the same answers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.freshness import freshness_note, names_table

REPORT = "vf_report_task_summary"

CASES = {
    # [sql, configured name, expected]
    "bare name": ("SELECT * FROM vf_report_task_summary", REPORT, True),
    "any case": ("select * from VF_Report_Task_Summary r", REPORT, True),
    "quoted": ('SELECT * FROM "vf_report_task_summary"', REPORT, True),
    "schema in the query": ("SELECT * FROM public.vf_report_task_summary", REPORT, True),
    "quoted schema and table": ('SELECT * FROM "public"."vf_report_task_summary"', REPORT, True),
    "in a join": ("SELECT t.task_id FROM tms_task_flat t JOIN vf_report_task_summary s "
                  "ON s.week = t.week", REPORT, True),
    "in a subquery": ("SELECT * FROM (SELECT week FROM vf_report_task_summary) x", REPORT, True),
    "in a CTE": ("WITH w AS (SELECT * FROM vf_report_task_summary) SELECT * FROM w",
                 REPORT, True),
    "another table": ("SELECT * FROM tms_task_flat", REPORT, False),
    "longer name": ("SELECT * FROM vf_report_task_summary_old", REPORT, False),
    "name inside another": ("SELECT * FROM x_vf_report_task_summary", REPORT, False),
    "only in a string literal": ("SELECT * FROM tms_task_flat WHERE title = "
                                 "'vf_report_task_summary'", REPORT, False),
    "only in a line comment": ("SELECT * FROM tms_task_flat -- not vf_report_task_summary\n",
                               REPORT, False),
    "only in a block comment": ("SELECT * /* vf_report_task_summary */ FROM tms_task_flat",
                                REPORT, False),
    "no SQL": (None, REPORT, False),
    "empty name": ("SELECT * FROM vf_report_task_summary", "", False),
    # A configured schema: that schema, or no schema, but not another one.
    "configured schema, same schema": ("SELECT * FROM public.vf_report_task_summary",
                                       "public." + REPORT, True),
    "configured schema, quoted": ('SELECT * FROM "public"."vf_report_task_summary"',
                                  "public." + REPORT, True),
    "configured schema, unqualified query": ("SELECT * FROM vf_report_task_summary",
                                             "public." + REPORT, True),
    "configured schema, other schema": ("SELECT * FROM archive.vf_report_task_summary",
                                        "public." + REPORT, False),
    "configured schema, typed in caps": ("SELECT * FROM public.vf_report_task_summary",
                                         "PUBLIC.VF_REPORT_TASK_SUMMARY", True),
}


@pytest.mark.parametrize("label", CASES)
def test_the_same_answer_as_drupal(label):
    sql, name, want = CASES[label]
    assert names_table(sql, name) is want


def _settings(tables=("tms_report_a", REPORT, "reports.weekly"),
              message="This data is not updated in real time."):
    return SimpleNamespace(freshness_tables=tables, freshness_message=message)


@pytest.mark.parametrize("sql,want", [
    ("SELECT * FROM vf_report_task_summary", True),   # second of three
    ("SELECT * FROM reports.weekly", True),           # third, qualified
    ("SELECT * FROM tms_task_flat", False),           # none of them
])
def test_any_one_configured_table_is_enough(sql, want):
    note = freshness_note(_settings(), [sql])
    assert (note == "This data is not updated in real time.") is want


def test_an_empty_sentence_turns_the_note_off():
    assert freshness_note(_settings(message="  "), ["SELECT * FROM vf_report_task_summary"]) is None


def test_no_tables_turns_the_note_off():
    assert freshness_note(_settings(tables=()), ["SELECT * FROM vf_report_task_summary"]) is None
