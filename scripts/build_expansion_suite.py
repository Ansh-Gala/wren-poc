"""Build and validate the 100-question expansion suite.

    python scripts/build_expansion_suite.py            # validate + write yaml
    python scripts/build_expansion_suite.py --dry-run  # validate only

The questions are defined here rather than hand-written as YAML so that every
one is executed against the database before it can enter the suite. A question
that errors, or that returns nothing when it was not meant to, is reported and
excluded rather than quietly shipped.

Wording is deliberately plain -- "How many are active?" rather than a paragraph.
The difficulty is meant to come from the data, the dimensions and the
conversational state, not from convoluted phrasing.

Row counts in the comments were taken from the database while writing.
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
OUT = ROOT / "benchmark" / "expansion_questions.yaml"

BO = "tms_business_object_flat"
TK = "tms_task_flat"
AT = "tms_business_object_attributes_flat"

# (id, category, question, sql, ordered, allow_zero)
# allow_zero marks a question whose correct answer is a count of 0 or an empty
# set -- a deliberate edge case rather than an oversight.
# Six candidates were cut to land on exactly 100 turns, each because a sibling
# already covered the same behaviour: E10, E23, E30, E45, E46, E60.
STANDALONE: list[tuple] = [
    # -- tier 1: simple ------------------------------------------------------
    ("E01", "Simple Count", "How many business objects are there?",
     f"SELECT COUNT(*) FROM {BO}", False, False),
    ("E02", "Simple Count", "How many business objects are active?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_status = 'Active'", False, False),
    ("E03", "Simple List", "Show AR_NPD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Suiting'", False, False),
    ("E04", "Simple Count", "How many AR_PD_Shirting items are there?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Shirting'", False, False),
    ("E05", "Status Filter", "Which AR_NPD_Shirting items are closed?",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Shirting' AND business_object_status = 'Closed'",
     False, False),
    ("E06", "Limit", "Show the first 10 AR_YD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting' LIMIT 10", False, False),
    ("E07", "Simple Count", "How many tasks are there?",
     f"SELECT COUNT(*) FROM {TK}", False, False),
    ("E08", "Simple Count", "How many tasks are closed?",
     f"SELECT COUNT(*) FROM {TK} WHERE task_status = 'closed'", False, False),
    ("E09", "Semantic Rule", "How many tasks are on time?",
     f"SELECT COUNT(*) FROM {TK} WHERE task_sla_status = 'On Time'", False, False),

    # -- tier 2: multiple filters -------------------------------------------
    ("E11", "Multi Filter", "Show active AR_PD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Shirting' AND business_object_status = 'Active'",
     False, False),
    ("E12", "Multi Filter", "How many AR_YD_Shirting items are black?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_YD_Shirting' "
     "AND business_object_color = 'Black'", False, False),
    ("E13", "Multi Filter", "Show closed AR_PD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Suiting' AND business_object_status = 'Closed'",
     False, False),
    ("E14", "Multi Filter", "How many active AR_NPD_YD_SHIRTING items are in unit1?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
     "AND business_object_status = 'Active' AND business_unit = 'unit1'", False, False),
    ("E15", "Multi Filter", "Show green AR_YD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_color = 'Green'",
     False, False),
    ("E16", "Multi Filter", "How many black AR_NPD_Shirting items are there?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_NPD_Shirting' "
     "AND business_object_color = 'Black'", False, False),
    ("E17", "Semantic Rule", "Show delayed tasks in AR_PRINT_Shirting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_PRINT_Shirting' AND task_sla_status = 'Delayed'",
     False, False),
    ("E18", "Multi Filter", "How many open tasks are in AR_NPD_Shirting?",
     f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_NPD_Shirting' "
     "AND task_status = 'open'", False, False),
    ("E19", "Multi Filter", "Show closed tasks in AR_PD_Suiting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_PD_Suiting' AND task_status = 'closed'", False, False),
    ("E20", "Semantic Rule", "How many delayed tasks are in AR_YD_Shirting?",
     f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_YD_Shirting' "
     "AND task_sla_status = 'Delayed'", False, False),

    # -- tier 3: grouping ----------------------------------------------------
    ("E21", "Grouping", "How many business objects are there by status?",
     f"SELECT business_object_status, COUNT(*) FROM {BO} GROUP BY business_object_status",
     False, False),
    ("E22", "Grouping", "How many business objects are there by type?",
     f"SELECT business_object_type, COUNT(*) FROM {BO} GROUP BY business_object_type",
     False, False),
    ("E24", "Grouping", "How many tasks are there by status?",
     f"SELECT task_status, COUNT(*) FROM {TK} GROUP BY task_status", False, False),
    ("E25", "Grouping", "How many tasks are there by SLA status?",
     f"SELECT task_sla_status, COUNT(*) FROM {TK} GROUP BY task_sla_status", False, False),
    ("E26", "Grouping", "How many tasks are there by department?",
     f"SELECT task_department, COUNT(*) FROM {TK} GROUP BY task_department", False, False),
    ("E27", "Grouping", "How many AR_YD_Suiting tasks are there by role?",
     f"SELECT assigned_role, COUNT(*) FROM {TK} "
     "WHERE business_object_type = 'AR_YD_Suiting' GROUP BY assigned_role", False, False),
    ("E28", "Grouping", "How many tasks does each business unit have?",
     f"SELECT business_unit, COUNT(*) FROM {TK} GROUP BY business_unit", False, False),
    ("E29", "Grouping", "How many AR_PD_Shirting items are there by status?",
     f"SELECT business_object_status, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Shirting' GROUP BY business_object_status",
     False, False),
    ("E31", "Grouping", "How many AR_YD_Shirting items are there by colour?",
     f"SELECT business_object_color, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting' GROUP BY business_object_color",
     False, False),
    ("E32", "Grouping", "How many business objects are there by business unit?",
     f"SELECT business_unit, COUNT(*) FROM {BO} GROUP BY business_unit", False, False),

    # -- tier 4: sorting and limits -----------------------------------------
    ("E33", "Sort + Limit", "Show the 5 oldest business objects",
     f"SELECT business_object_id, business_object_created_at FROM {BO} "
     "ORDER BY business_object_created_at ASC LIMIT 5", True, False),
    ("E34", "Ranking", "Which 3 business object types have the most items?",
     f"SELECT business_object_type, COUNT(*) AS n FROM {BO} "
     "GROUP BY business_object_type ORDER BY n DESC LIMIT 3", True, False),
    ("E35", "Filter + Limit", "Show the first 5 delayed tasks",
     f"SELECT task_id, task_display_name FROM {TK} WHERE task_sla_status = 'Delayed' LIMIT 5",
     False, False),
    ("E36", "Sort", "Show AR_NPD_Suiting items sorted by id",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Suiting' ORDER BY business_object_id", True, False),
    ("E37", "Ranking", "Which business object has the most tasks?",
     f"SELECT business_object_id, total_task_count FROM {BO} "
     "ORDER BY total_task_count DESC LIMIT 1", True, False),
    ("E38", "Sort + Limit", "Show the 10 most recently created business objects",
     f"SELECT business_object_id, business_object_created_at FROM {BO} "
     "ORDER BY business_object_created_at DESC LIMIT 10", True, False),
    ("E39", "Ranking", "Which 3 departments have the most tasks?",
     f"SELECT task_department, COUNT(*) AS n FROM {TK} "
     "GROUP BY task_department ORDER BY n DESC LIMIT 3", True, False),
    ("E40", "Ranking", "Show the 5 business objects with the most delayed tasks",
     f"SELECT business_object_id, delayed_task_count FROM {BO} "
     "ORDER BY delayed_task_count DESC LIMIT 5", True, False),

    # -- tier 5: joins and cross-dimension ----------------------------------
    ("E41", "Join", "Show AR_NPD_Suiting items with their vendor",
     f"SELECT b.business_object_id, b.business_object_ref_id, a.vendor FROM {BO} b "
     f"JOIN {AT} a ON a.business_object_id = b.business_object_id "
     "WHERE b.business_object_type = 'AR_NPD_Suiting'", False, False),
    ("E42", "Join", "How many business objects have a vendor recorded?",
     f"SELECT COUNT(*) FROM {AT} WHERE vendor IS NOT NULL", False, False),
    ("E43", "Join", "Show AR_YD_Suiting items with their category and season",
     f"SELECT b.business_object_id, a.category, a.season FROM {BO} b "
     f"JOIN {AT} a ON a.business_object_id = b.business_object_id "
     "WHERE b.business_object_type = 'AR_YD_Suiting'", False, False),
    ("E44", "Cross Dimension", "Which users belong to more than one department?",
     "SELECT user_id, user_name, department_count FROM tms_user_flat WHERE department_count > 1",
     False, False),
    ("E47", "Cross Dimension", "Which business objects have delayed tasks?",
     f"SELECT business_object_id, delayed_task_count FROM {BO} WHERE delayed_task_count > 0",
     False, False),
    ("E48", "Join", "How many AR_YD_Suiting items have a vendor?",
     f"SELECT COUNT(*) FROM {BO} b JOIN {AT} a ON a.business_object_id = b.business_object_id "
     "WHERE b.business_object_type = 'AR_YD_Suiting' AND a.vendor IS NOT NULL", False, False),

    # -- tier 6: edge cases, nulls, boundaries ------------------------------
    # status is NULL for 6 rows and never the empty string, so an OR on '' was
    # dead weight that made a correct answer look semantically different.
    ("E49", "Null Handling", "How many business objects have no status recorded?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_status IS NULL", False, False),
    ("E50", "Null Handling", "How many business objects have a note?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_note IS NOT NULL", False, False),
    ("E51", "Boundary", "How many tasks have been reopened?",
     f"SELECT COUNT(*) FROM {TK} WHERE reopen_count > 0", False, False),
    ("E52", "Boundary", "How many tasks are hidden from display?",
     f"SELECT COUNT(*) FROM {TK} WHERE display_flag = 0", False, False),
    ("E53", "Edge Case", "How many business objects are short closed?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_status = 'Short Closed'", False, False),
    ("E54", "Boundary", "How many business objects are past their due date?",
     f"SELECT COUNT(*) FROM {BO} WHERE days_to_due_date < 0", False, False),
    ("E55", "Null Handling", "How many business objects have no workflow name?",
     f"SELECT COUNT(*) FROM {BO} WHERE workflow_name IS NULL", False, False),
    ("E56", "Null Handling", "How many tasks have no department?",
     f"SELECT COUNT(*) FROM {TK} WHERE task_department IS NULL", False, False),
    ("E57", "Empty Result", "How many business objects have a quality value?",
     f"SELECT COUNT(*) FROM {AT} WHERE quality IS NOT NULL", False, True),
    ("E58", "Empty Result", "How many tasks have not started yet?",
     f"SELECT COUNT(*) FROM {TK} WHERE is_not_started_task", False, True),
    ("E59", "Distinct", "How many different departments are there?",
     f"SELECT COUNT(DISTINCT task_department) FROM {TK}", False, False),
]

# (conversation id, category, [(turn id, question, sql, decision, ordered)])
CONVERSATIONS: list[tuple] = [
    ("X01", "Conversation - Filter then Group", [
        ("X01.1", "Show AR_PD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting'", "new_block", False),
        ("X01.2", "Only the active ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting' AND business_object_status = 'Active'",
         "follow_up", False),
        ("X01.3", "How many?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Shirting' "
         "AND business_object_status = 'Active'", "follow_up", False),
        ("X01.4", "Group them by colour",
         f"SELECT business_object_color, COUNT(*) FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting' AND business_object_status = 'Active' "
         "GROUP BY business_object_color", "follow_up", False),
    ]),
    ("X02", "Conversation - Task Thread", [
        ("X02.1", "Show tasks in AR_YD_Shirting",
         f"SELECT task_id, task_display_name, task_status FROM {TK} "
         "WHERE business_object_type = 'AR_YD_Shirting'", "new_block", False),
        ("X02.2", "Only the open ones",
         f"SELECT task_id, task_display_name, task_status FROM {TK} "
         "WHERE business_object_type = 'AR_YD_Shirting' AND task_status = 'open'",
         "follow_up", False),
        ("X02.3", "How many?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_YD_Shirting' "
         "AND task_status = 'open'", "follow_up", False),
        ("X02.4", "Group them by department",
         f"SELECT task_department, COUNT(*) FROM {TK} "
         "WHERE business_object_type = 'AR_YD_Shirting' AND task_status = 'open' "
         "GROUP BY task_department", "follow_up", False),
    ]),
    ("X03", "Conversation - Replace and Remove", [
        ("X03.1", "Show active AR_NPD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting' AND business_object_status = 'Active'",
         "new_block", False),
        ("X03.2", "Show the closed ones instead",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting' AND business_object_status = 'Closed'",
         "follow_up", False),
        ("X03.3", "Remove the status filter",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting'", "follow_up", False),
    ]),
    ("X04", "Conversation - Narrow then Sort", [
        ("X04.1", "Show AR_YD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting'", "new_block", False),
        ("X04.2", "Only the black ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_color = 'Black'",
         "follow_up", False),
        ("X04.3", "How many are there?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_YD_Suiting' "
         "AND business_object_color = 'Black'", "follow_up", False),
        ("X04.4", "Sort them by id",
         f"SELECT business_object_id, business_object_ref_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_color = 'Black' "
         "ORDER BY business_object_id", "follow_up", True),
        ("X04.5", "Just the first 5",
         f"SELECT business_object_id, business_object_ref_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_color = 'Black' "
         "ORDER BY business_object_id LIMIT 5", "follow_up", True),
    ]),
    ("X05", "Conversation - Topic Switch", [
        ("X05.1", "Show AR_PD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Suiting'", "new_block", False),
        ("X05.2", "Only the active ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Suiting' AND business_object_status = 'Active'",
         "follow_up", False),
        ("X05.3", "Show AR_NPD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting'", "switch", False),
        ("X05.4", "Only the closed ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting' AND business_object_status = 'Closed'",
         "follow_up", False),
    ]),
    ("X06", "Conversation - Explicit Reset", [
        ("X06.1", "Show AR_PRINT_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting'", "new_block", False),
        ("X06.2", "How many?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PRINT_Shirting'",
         "follow_up", False),
        ("X06.3", "New question: how many AR_PD_Suiting items are there?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Suiting'",
         "new_block", False),
    ]),
    ("X07", "Conversation - Dimension Switch", [
        ("X07.1", "Show AR_NPD_YD_SHIRTING items",
         f"SELECT business_object_id, business_object_ref_id, business_unit FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "new_block", False),
        ("X07.2", "What about PVH?",
         f"SELECT business_object_id, business_object_ref_id, business_unit FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' AND business_unit = 'PVH'",
         "follow_up", False),
        ("X07.3", "And unit1?",
         f"SELECT business_object_id, business_object_ref_id, business_unit FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' AND business_unit = 'unit1'",
         "follow_up", False),
    ]),
    ("X08", "Conversation - Group then List", [
        ("X08.1", "How many TESTING_MG items are there by status?",
         f"SELECT business_object_status, COUNT(*) FROM {BO} "
         "WHERE business_object_type = 'TESTING_MG' GROUP BY business_object_status",
         "new_block", False),
        ("X08.2", "Just list them instead",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'TESTING_MG'", "follow_up", False),
        ("X08.3", "Only the active ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'TESTING_MG' AND business_object_status = 'Active'",
         "follow_up", False),
        ("X08.4", "How many is that?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'TESTING_MG' "
         "AND business_object_status = 'Active'", "follow_up", False),
    ]),
    ("X09", "Conversation - Limit Changes", [
        ("X09.1", "Show the first 3 AR_PRINT_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting' LIMIT 3", "new_block", False),
        ("X09.2", "Make that 10",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting' LIMIT 10", "follow_up", False),
        ("X09.3", "Show all of them",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PRINT_Shirting'", "follow_up", False),
    ]),
    ("X10", "Conversation - Return to Topic", [
        ("X10.1", "Show AR_YD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting'", "new_block", False),
        ("X10.2", "Show AR_NPD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting'", "switch", False),
        ("X10.3", "Back to AR_YD_Suiting, how many are active?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_YD_Suiting' "
         "AND business_object_status = 'Active'", "switch", False),
    ]),
    ("X11", "Conversation - Stack then Unstack", [
        ("X11.1", "Show AR_NPD_YD_SHIRTING items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "new_block", False),
        ("X11.2", "Only the active ones",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active'", "follow_up", False),
        ("X11.3", "Only the black ones too",
         f"SELECT business_object_id, business_object_ref_id, business_object_color FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", False),
        ("X11.4", "Drop the colour filter",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active'", "follow_up", False),
    ]),
    ("X12", "Conversation - Projection Change", [
        ("X12.1", "Show AR_NPD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting'", "new_block", False),
        ("X12.2", "Show their status too",
         f"SELECT business_object_id, business_object_ref_id, business_object_status FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Suiting'", "follow_up", False),
        ("X12.3", "And their colour",
         f"SELECT business_object_id, business_object_ref_id, business_object_status, "
         f"business_object_color FROM {BO} WHERE business_object_type = 'AR_NPD_Suiting'",
         "follow_up", False),
    ]),
    ("X13", "Conversation - Pronoun Reference", [
        ("X13.1", "Show delayed tasks in AR_PD_Shirting",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE business_object_type = 'AR_PD_Shirting' AND task_sla_status = 'Delayed'",
         "new_block", False),
        ("X13.2", "Count them",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_PD_Shirting' "
         "AND task_sla_status = 'Delayed'", "follow_up", False),
        ("X13.3", "Group them by department",
         f"SELECT task_department, COUNT(*) FROM {TK} "
         "WHERE business_object_type = 'AR_PD_Shirting' AND task_sla_status = 'Delayed' "
         "GROUP BY task_department", "follow_up", False),
    ]),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())

    errors: list[str] = []
    empties: list[str] = []
    questions: list[dict] = []

    def check(qid: str, sql: str, allow_zero: bool) -> bool:
        res = run_readonly(settings, sql, settings.statement_timeout_ms)
        if res.error:
            errors.append(f"{qid}: {res.error.splitlines()[0]}")
            return False
        if not res.rows and not allow_zero:
            empties.append(qid)
            return False
        return True

    for qid, cat, question, sql, ordered, allow_zero in STANDALONE:
        ok = check(qid, sql, allow_zero)
        entry = {"id": qid, "category": cat, "question": question, "expected_sql": sql + "\n"}
        if ordered:
            entry["ordered"] = True
        if allow_zero:
            entry["tags"] = ["edge_case"]
        if ok:
            questions.append(entry)

    for cid, cat, turns in CONVERSATIONS:
        built = []
        for tid, question, sql, decision, ordered in turns:
            ok = check(tid, sql, False)
            e = {"id": tid, "question": question, "expect_decision": decision,
                 "expected_sql": sql + "\n"}
            if ordered:
                e["ordered"] = True
            if ok:
                built.append(e)
        if len(built) == len(turns):
            questions.append({"id": cid, "category": cat, "turns": built})
        else:
            errors.append(f"{cid}: dropped, {len(turns) - len(built)} turn(s) invalid")

    n_turns = sum(len(q["turns"]) if "turns" in q else 1 for q in questions)
    print(f"standalone: {len(STANDALONE)}   conversations: {len(CONVERSATIONS)}")
    print(f"valid turns: {n_turns}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    if empties:
        print(f"\nEMPTY ({len(empties)}): {', '.join(empties)}")
    if errors or empties:
        print("\nfix these before writing the suite")
        return 1

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    header = (
        "# Expansion suite: discovery and edge cases, generated and validated by\n"
        "# scripts/build_expansion_suite.py. Every query here was executed against\n"
        "# arvind_retail_chatbot_test_1 before the question was accepted.\n"
        "#\n"
        "# Wording is deliberately plain. The difficulty is meant to come from the\n"
        "# data, the dimensions and the conversational state, not from the phrasing.\n"
        "#\n"
        "# Questions tagged edge_case are expected to return a count of zero: that\n"
        "# is the correct answer, not a broken question.\n"
    )
    OUT.write_text(
        header + yaml.safe_dump({"version": 1, "questions": questions},
                                sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT.relative_to(ROOT)}: {n_turns} turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
