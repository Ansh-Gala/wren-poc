"""Build and validate the targeted suite: one group per failure mode.

    python scripts/build_targeted_suite.py [--dry-run]

The lean suite is the regression net and the expansion suite is broad
discovery. Neither aims at a specific weakness. This one does: each group
exists because a particular way of being wrong was not otherwise being
measured.

  clarification   the system had no way to say "I don't know", so it guessed,
                  and a guess dressed as SQL is indistinguishable from an
                  answer. These questions have no valid answer, or more than
                  one, and asking is the correct behaviour.
  hallucination   asked for something absent, a model may invent a column.
                  Checked against the schema, not judged by eye.
  complex filters three and four dimensions at once, where dropping one
                  silently still returns plausible rows.
  dates           boundaries and ranges, where off-by-one is invisible in the
                  row count unless the boundary was chosen to expose it.
  zero results    the correct answer is nothing. A system that quietly relaxes
                  a filter to avoid an empty answer is worse than one that
                  returns none.
  state isolation the conversational cases the other suites touch once each.

Every query is executed before the question is accepted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from config.logging import register_secrets
from config.settings import load_settings
from database.connection import run_readonly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark" / "targeted_questions.yaml"

BO = "tms_business_object_flat"
TK = "tms_task_flat"
AT = "tms_business_object_attributes_flat"

# Questions with no answerable form. expected_sql is None and the system is
# expected to ask rather than produce SQL.
CLARIFY = [
    ("T01", "Clarification - No Such Measure", "What is the revenue by business unit?"),
    ("T02", "Clarification - No Such Measure", "Show the profit margin for each item"),
    ("T03", "Clarification - No Such Measure", "What is the average cost of an item?"),
    ("T04", "Clarification - No Such Concept", "How many orders did we ship last month?"),
    ("T05", "Clarification - No Such Concept", "Which suppliers are underperforming?"),
    ("T06", "Clarification - Ambiguous", "Show me the items"),
    ("T07", "Clarification - Ambiguous", "Which ones are urgent?"),
    ("T08", "Clarification - Ambiguous", "Show me the top performers"),
    ("T09", "Clarification - No Such Column", "Show the discount applied to each item"),
    ("T10", "Clarification - No Such Column", "What is the customer email for each order?"),
]

# (id, category, question, sql, ordered, allow_zero)
STANDALONE = [
    # -- hallucination resistance: real columns, values that do not occur -----
    ("T11", "Hallucination - Absent Value", "Show items whose colour is Purple",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_color = 'Purple'", False, True),
    ("T12", "Hallucination - Absent Value", "How many AR_FAKE_TYPE items are there?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_FAKE_TYPE'", False, True),
    ("T13", "Hallucination - Absent Value", "Show tasks with SLA status Breached",
     f"SELECT task_id FROM {TK} WHERE task_sla_status = 'Breached'", False, True),
    ("T14", "Hallucination - Absent Value", "How many items are in business unit unit9?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_unit = 'unit9'", False, True),

    # -- complex filter combinations ----------------------------------------
    ("T15", "Complex Filter", "How many active black AR_YD_Suiting items are in unit1?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_YD_Suiting' "
     "AND business_object_status = 'Active' AND business_object_color = 'Black' "
     "AND business_unit = 'unit1'", False, False),
    ("T16", "Complex Filter", "Show active green AR_YD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting' AND business_object_status = 'Active' "
     "AND business_object_color = 'Green'", False, False),
    ("T17", "Complex Filter", "How many open delayed tasks are in AR_PRINT_Shirting?",
     f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_PRINT_Shirting' "
     "AND task_status = 'open' AND task_sla_status = 'Delayed'", False, False),
    ("T18", "Complex Filter", "Show closed on-time tasks in AR_PD_Shirting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_PD_Shirting' AND task_status = 'closed' "
     "AND task_sla_status = 'On Time'", False, False),
    ("T19", "Complex Filter", "How many closed black AR_PD_Shirting items are there?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Shirting' "
     "AND business_object_status = 'Closed' AND business_object_color = 'Black'",
     False, False),
    ("T20", "Complex Filter", "How many active items are black across all types?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_status = 'Active' "
     "AND business_object_color = 'Black'", False, False),
    ("T21", "Complex Filter + Null",
     "How many business objects have no workflow name but are active?",
     f"SELECT COUNT(*) FROM {BO} WHERE workflow_name IS NULL "
     "AND business_object_status = 'Active'", False, False),
    ("T22", "Complex Filter + Group",
     "How many active items are there by colour and business unit?",
     f"SELECT business_object_color, business_unit, COUNT(*) FROM {BO} "
     "WHERE business_object_status = 'Active' "
     "GROUP BY business_object_color, business_unit", False, False),

    # -- dates ---------------------------------------------------------------
    ("T23", "Date Filter", "How many business objects were created before May 2026?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at < DATE '2026-05-01'",
     False, False),
    ("T24", "Date Filter", "How many business objects were created after June 2026 began?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-06-01'",
     False, False),
    ("T25", "Date Range", "How many business objects were created in March 2026?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-03-01' "
     "AND business_object_created_at < DATE '2026-04-01'", False, False),
    ("T26", "Date Range",
     "How many business objects were created between April and June 2026?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-04-01' "
     "AND business_object_created_at < DATE '2026-07-01'", False, False),
    ("T27", "Date Semantic", "How many business objects are past their due date?",
     f"SELECT COUNT(*) FROM {BO} WHERE days_to_due_date < 0", False, False),
    ("T28", "Date Semantic", "How many active business objects are overdue?",
     f"SELECT COUNT(*) FROM {BO} WHERE days_to_due_date < 0 "
     "AND business_object_status = 'Active'", False, False),
    ("T29", "Date Semantic", "How many business objects are due within the next 30 days?",
     f"SELECT COUNT(*) FROM {BO} WHERE days_to_due_date BETWEEN 0 AND 30", False, False),
    # "closed in June" was ambiguous by one row: a task closed in June was
    # later reopened, so it has a June closing date but is not closed now.
    # The model read it the stricter way, which is defensible. Say which.
    ("T30", "Date Filter", "How many tasks have a closing date in June 2026?",
     f"SELECT COUNT(*) FROM {TK} WHERE task_closed_at >= DATE '2026-06-01' "
     "AND task_closed_at < DATE '2026-07-01'", False, False),
    ("T31", "Date Sort", "Show the 3 oldest AR_YD_Suiting items",
     f"SELECT business_object_id, business_object_created_at FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' "
     "ORDER BY business_object_created_at ASC LIMIT 3", True, False),

    # -- genuinely zero ------------------------------------------------------
    ("T32", "Zero Result", "How many AR_YD_Suiting items are short closed?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_YD_Suiting' "
     "AND business_object_status = 'Short Closed'", False, True),
    ("T33", "Zero Result", "Show AR_NPD_Shirting items in PVH",
     f"SELECT business_object_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Shirting' AND business_unit = 'PVH'",
     False, True),
    ("T34", "Zero Result", "How many AR_YD_Suiting items have a season recorded?",
     f"SELECT COUNT(*) FROM {BO} b JOIN {AT} a ON a.business_object_id = b.business_object_id "
     "WHERE b.business_object_type = 'AR_YD_Suiting' AND a.season IS NOT NULL",
     False, True),

    # -- projection precision ------------------------------------------------
    ("T35", "Projection", "Show only the ids of active AR_YD_Suiting items",
     f"SELECT business_object_id FROM {BO} WHERE business_object_type = 'AR_YD_Suiting' "
     "AND business_object_status = 'Active'", False, False),
    ("T36", "Projection", "List the reference ids of closed AR_NPD_Shirting items",
     f"SELECT business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Shirting' AND business_object_status = 'Closed'",
     False, False),
    ("T37", "Projection", "Show the id and status of AR_NPD_Suiting items",
     f"SELECT business_object_id, business_object_status FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Suiting'", False, False),
]

CONVERSATIONS = [
    ("Y01", "State - Aggregation Switch", [
        ("Y01.1", "Show AR_PD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Suiting'", "new_block", False),
        ("Y01.2", "How many?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Suiting'",
         "follow_up", False),
        ("Y01.3", "List them again",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Suiting'", "follow_up", False),
    ]),
    ("Y02", "State - Dimension Replace", [
        ("Y02.1", "Show black AR_YD_Shirting items",
         f"SELECT business_object_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' AND business_object_color = 'Black'",
         "new_block", False),
        ("Y02.2", "Show the green ones instead",
         f"SELECT business_object_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' AND business_object_color = 'Green'",
         "follow_up", False),
        ("Y02.3", "Now only the active ones",
         f"SELECT business_object_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' AND business_object_color = 'Green' "
         "AND business_object_status = 'Active'", "follow_up", False),
    ]),
    ("Y03", "State - Leakage After Switch", [
        ("Y03.1", "Show active AR_PRINT_Shirting items",
         f"SELECT business_object_id FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting' "
         "AND business_object_status = 'Active'", "new_block", False),
        ("Y03.2", "Only the black ones",
         f"SELECT business_object_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", False),
        ("Y03.3", "Show AR_NPD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting'", "switch", False),
        ("Y03.4", "How many?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_NPD_Suiting'",
         "follow_up", False),
    ]),
    ("Y04", "State - Sort then Change Sort", [
        ("Y04.1", "Show AR_NPD_Suiting items sorted by id",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting' ORDER BY business_object_id",
         "new_block", True),
        ("Y04.2", "Sort them the other way",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting' ORDER BY business_object_id DESC",
         "follow_up", True),
        ("Y04.3", "Just the first 3",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting' ORDER BY business_object_id DESC "
         "LIMIT 3", "follow_up", True),
    ]),
    ("Y05", "State - Task Domain Switch", [
        ("Y05.1", "Show delayed tasks in AR_NPD_Suiting",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE business_object_type = 'AR_NPD_Suiting' AND task_sla_status = 'Delayed'",
         "new_block", False),
        ("Y05.2", "How many?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_NPD_Suiting' "
         "AND task_sla_status = 'Delayed'", "follow_up", False),
        ("Y05.3", "What about AR_PD_Suiting?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_PD_Suiting' "
         "AND task_sla_status = 'Delayed'", "switch", False),
    ]),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())

    errors: list[str] = []
    surprises: list[str] = []
    questions: list[dict] = []

    def check(qid: str, sql: str, allow_zero: bool) -> bool:
        res = run_readonly(settings, sql, settings.statement_timeout_ms)
        if res.error:
            errors.append(f"{qid}: {res.error.splitlines()[0]}")
            return False
        empty = not res.rows or (len(res.rows) == 1 and res.rows[0][0] == 0)
        if empty and not allow_zero:
            surprises.append(f"{qid}: expected rows, got none")
            return False
        if not empty and allow_zero:
            surprises.append(f"{qid}: expected zero, got {len(res.rows)} row(s)")
            return False
        return True

    for qid, cat, question in CLARIFY:
        questions.append({
            "id": qid, "category": cat, "question": question,
            "expect_behavior": "clarify", "expected_sql": None,
            "note": "No valid SQL answer. The system should ask rather than guess.",
        })

    # These name a value the column does not have. Two answers are defensible:
    # return nothing, or say the value does not exist. Both are accepted; what
    # is not is substituting a value that does exist in order to return rows.
    ABSENT_VALUE = {"T11", "T12", "T13", "T14"}

    for qid, cat, question, sql, ordered, allow_zero in STANDALONE:
        ok = check(qid, sql, allow_zero)
        e = {"id": qid, "category": cat, "question": question, "expected_sql": sql + "\n"}
        if ordered:
            e["ordered"] = True
        if qid in ABSENT_VALUE:
            e["expect_behavior"] = "zero_or_clarify"
            e["tags"] = ["absent_value"]
            e["note"] = ("The value does not exist. Returning nothing and saying so are "
                         "both correct; substituting a real value to produce rows is not.")
        elif allow_zero:
            e["tags"] = ["zero_result"]
            e["note"] = "Zero is the correct answer; relaxing a filter to avoid it is wrong."
        if ok:
            questions.append(e)

    for cid, cat, turns in CONVERSATIONS:
        built = []
        for tid, question, sql, decision, ordered in turns:
            if check(tid, sql, False):
                e = {"id": tid, "question": question, "expect_decision": decision,
                     "expected_sql": sql + "\n"}
                if ordered:
                    e["ordered"] = True
                built.append(e)
        if len(built) == len(turns):
            questions.append({"id": cid, "category": cat, "turns": built})
        else:
            errors.append(f"{cid}: dropped, {len(turns) - len(built)} turn(s) invalid")

    n = sum(len(q["turns"]) if "turns" in q else 1 for q in questions)
    print(f"clarification: {len(CLARIFY)}   standalone: {len(STANDALONE)}   "
          f"conversations: {len(CONVERSATIONS)}")
    print(f"valid turns: {n}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    if surprises:
        print(f"\nUNEXPECTED CARDINALITY ({len(surprises)}):")
        for s in surprises:
            print(f"  {s}")
    if errors or surprises:
        return 1

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    header = (
        "# Targeted suite: one group per failure mode, generated and validated by\n"
        "# scripts/build_targeted_suite.py.\n"
        "#\n"
        "# Questions with expect_behavior: clarify have no valid SQL answer. Asking\n"
        "# is the correct response; producing confident SQL is the failure.\n"
        "#\n"
        "# Questions tagged zero_result are expected to return nothing. That is the\n"
        "# right answer, and quietly dropping a filter to avoid it is not.\n"
    )
    OUT.write_text(
        header + yaml.safe_dump({"version": 1, "questions": questions},
                                sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}: {n} turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
