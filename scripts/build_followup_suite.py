"""Build and validate the follow-up suite.

    python scripts/build_followup_suite.py [--dry-run]

The other three suites ask whether the system writes the right SQL. This one
asks what it does around the SQL: whether it repairs a misspelling instead of
guessing, asks which of several things was meant instead of picking one, and
offers a next move worth taking instead of a generic one.

Every case is validated before it is written, and validated in the way that
matches what it claims:

  repair       the repair layer is run and must produce the stated question.
               A case whose typo the layer does not catch is a case that would
               silently pass for the wrong reason.
  clarify      no SQL, so nothing to execute; the case asserts behaviour.
  exploration  the suggestion generator is run against the state that the
               expected SQL produces, and the expected action must be among
               what it offers. Without this the benchmark would assert
               suggestions the system has no way to make.
  sql          executed against the live database, like every other suite.

That last check is the reason this file is a builder rather than hand-written
YAML: an expectation nobody can satisfy is worse than no expectation, because
it looks like a finding.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from benchmark.context import ConversationState, update_state
from benchmark.followup import clarify_entity, explore
from benchmark.normalize import normalize
from config.logging import register_secrets
from config.settings import load_settings
from database.connection import run_readonly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark" / "followup_questions.yaml"

BO = "tms_business_object_flat"
TK = "tms_task_flat"
AT = "tms_business_object_attributes_flat"
UD = "tms_user_department_flat"

# ---------------------------------------------------------------- A. repair --
# What the user typed, what it means, and the SQL that answers it. The typo in
# every one of these is a real one -- a transposition, a dropped letter, a
# doubled letter -- not a random mutation.
#
# (id, category, typed, normalized, sql)
REPAIR = [
    ("F01", "Repair - Typo", "show my delyaed tasks", "show my delayed tasks",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE assigned_user_id = 1 AND task_sla_status = 'Delayed'"),
    ("F02", "Repair - Typo", "how many taks are open", "how many tasks are open",
     f"SELECT COUNT(*) FROM {TK} WHERE task_status = 'open'"),
    ("F03", "Repair - Typo", "show clsoed AR_YD_Suiting items",
     "show closed AR_YD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_status = 'Closed'"),
    ("F04", "Repair - Typo", "list activ AR_NPD_Shirting items",
     "list active AR_NPD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_Shirting' AND business_object_status = 'Active'"),
    ("F05", "Repair - Transposition", "show the AR_YD_Suiting itmes",
     "show the AR_YD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting'"),
    ("F06", "Repair - Typo", "how many AR_YD_Suiting items are there by staus?",
     "how many AR_YD_Suiting items are there by status?",
     f"SELECT business_object_status, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' GROUP BY business_object_status"),
    ("F07", "Repair - Typo", "how many bussiness objects are there",
     "how many business objects are there",
     f"SELECT COUNT(*) FROM {BO}"),
    ("F08", "Repair - Typo", "which AR_PD_Suiting tasks are delayd",
     "which AR_PD_Suiting tasks are delayed",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_PD_Suiting' AND task_sla_status = 'Delayed'"),
    ("F09", "Repair - Typo", "how many items have no workfow name",
     "how many items have no workflow name",
     f"SELECT COUNT(*) FROM {BO} WHERE workflow_name IS NULL"),
    ("F10", "Repair - Typo", "how many sutiing items are active?",
     "how many suiting items are active?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type LIKE '%Suiting' "
     "AND business_object_status = 'Active'"),
    ("F11", "Repair - Typo", "show AR_YD_Suiting items with satus Closed",
     "show AR_YD_Suiting items with status Closed",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' AND business_object_status = 'Closed'"),
    ("F12", "Repair - Typo", "list the delaied AR_NPD_Suiting tasks",
     "list the delayed AR_NPD_Suiting tasks",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_NPD_Suiting' AND task_sla_status = 'Delayed'"),
    ("F13", "Repair - Typo", "how many items are in buisness unit unit1",
     "how many items are in business unit unit1",
     f"SELECT COUNT(*) FROM {BO} WHERE business_unit = 'unit1'"),
    ("F14", "Repair - Transposition", "how many objets are active",
     "how many objects are active",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_status = 'Active'"),
    ("F15", "Repair - Transposition", "show open tsaks in AR_YD_Suiting",
     "show open tasks in AR_YD_Suiting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_YD_Suiting' AND task_status = 'open'"),
    ("F16", "Repair - Transposition", "how many usres are there",
     "how many users are there",
     "SELECT COUNT(*) FROM tms_user_flat"),
    ("F17", "Repair - Spelling Variant", "how many AR_YD_Shirting items are there by colur?",
     "how many AR_YD_Shirting items are there by color?",
     f"SELECT business_object_color, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting' GROUP BY business_object_color"),
    ("F18", "Repair - Typo", "show the seasosn on record", "show the season on record",
     f"SELECT DISTINCT season FROM {AT} WHERE season IS NOT NULL"),
    ("F19", "Repair - Typo", "how many AR_PD_Shirting items are shirtng",
     "how many AR_PD_Shirting items are shirting",
     f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_PD_Shirting'"),
    ("F20", "Repair - Typo", "show the assigend user for each open AR_NPD_Suiting task",
     "show the assigned user for each open AR_NPD_Suiting task",
     f"SELECT task_id, assigned_user_name FROM {TK} "
     "WHERE business_object_type = 'AR_NPD_Suiting' AND task_status = 'open'"),
]

# --------------------------------------------------- B. clarification ------
# A partial name that matches several real types. The system must ask which,
# and the candidates it offers must all exist.
#
# (id, question, expected_action_value)
AMBIGUOUS_ENTITY = [
    ("F21", "Show the AR_YD items", "AR_YD_Suiting"),
    ("F22", "How many AR_NPD items are there?", "AR_NPD_Shirting"),
    ("F23", "Show the SALESPLAN items", "AR_SALESPLAN_Suiting"),
    ("F24", "Give me the PRINT items", "AR_PRINT_Suiting"),
    ("F25", "Show AR_PD items", "AR_PD_Suiting"),
]

# No answerable form at all: the schema holds no such measure or column.
NO_SUCH_THING = [
    ("F26", "Clarify - No Such Measure", "What is the total revenue for AR_YD_Suiting?"),
    ("F27", "Clarify - No Such Measure", "Show the unit cost of each item"),
    ("F28", "Clarify - No Such Measure", "What is the profit on closed items?"),
    ("F29", "Clarify - No Such Column", "Show the customer email for each item"),
    ("F30", "Clarify - No Such Column", "What discount was applied to each order?"),
    ("F31", "Clarify - No Such Column", "Show the shipping address for each item"),
    ("F32", "Clarify - No Such Concept", "Which vendors missed their contract terms?"),
    ("F33", "Clarify - No Such Concept", "How many items were returned by customers?"),
    ("F34", "Clarify - Ambiguous", "Show me the important ones"),
    ("F35", "Clarify - Ambiguous", "Which items are doing badly?"),
]

# A real column, a value it does not take. Returning nothing is honest;
# substituting a value that does exist is the failure being measured.
UNKNOWN_VALUE = [
    ("F36", "Show tasks whose SLA status is Breached",
     f"SELECT task_id FROM {TK} WHERE task_sla_status = 'Breached'"),
    ("F37", "Show items whose status is Pending",
     f"SELECT business_object_id FROM {BO} WHERE business_object_status = 'Pending'"),
    ("F38", "Show items whose colour is Purple",
     f"SELECT business_object_id FROM {BO} WHERE business_object_color = 'Purple'"),
    ("F39", "How many items are in business unit unit7?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_unit = 'unit7'"),
    ("F40", "Show tasks whose status is archived",
     f"SELECT task_id FROM {TK} WHERE task_status = 'archived'"),
]

# ----------------------------------------------------- C. exploration ------
# Answerable questions, each paired with a continuation the system should be
# offering afterwards. The action is checked against what the generator
# actually produces for the state the expected SQL creates, so none of these
# asserts a suggestion that cannot be made.
#
# (id, category, question, sql, expected_action)
EXPLORATION = [
    ("F41", "Explore - Narrow a List", "Show the AR_YD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F42", "Explore - Narrow a List", "Show the AR_YD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F43", "Explore - Group a List", "Show the AR_NPD_YD_SHIRTING items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'",
     {"type": "add_group_by", "field": "business_unit"}),
    ("F44", "Explore - Sort a List", "Show the AR_PD_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Shirting'",
     {"type": "set_sort", "field": "business_object_client_due_at"}),
    ("F45", "Explore - Count a List", "Show the AR_PD_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Suiting'",
     {"type": "set_aggregate"}),
    ("F46", "Explore - Narrow Tasks", "Show the tasks in AR_YD_Suiting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_YD_Suiting'",
     {"type": "add_filter", "field": "task_status"}),
    ("F47", "Explore - Narrow Tasks", "Show the tasks in AR_PD_Shirting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_PD_Shirting'",
     {"type": "add_filter", "field": "task_status"}),
    ("F48", "Explore - Drop a Filter", "Show active AR_YD_Suiting items in unit1",
     f"SELECT business_object_id FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' "
     "AND business_object_status = 'Active' AND business_unit = 'unit1'",
     {"type": "remove_filter"}),
    ("F49", "Explore - Drop a Filter", "Show closed black AR_PD_Shirting items",
     f"SELECT business_object_id FROM {BO} "
     "WHERE business_object_type = 'AR_PD_Shirting' "
     "AND business_object_status = 'Closed' AND business_object_color = 'Black'",
     {"type": "remove_filter"}),
    ("F50", "Explore - Drill Down", "How many AR_YD_Suiting items are there by status?",
     f"SELECT business_object_status, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Suiting' GROUP BY business_object_status",
     {"type": "drill_down"}),
    ("F51", "Explore - Drill Down", "How many AR_YD_Shirting items are there by colour?",
     f"SELECT business_object_color, COUNT(*) FROM {BO} "
     "WHERE business_object_type = 'AR_YD_Shirting' GROUP BY business_object_color",
     {"type": "drill_down"}),
    ("F52", "Explore - Drill Down", "How many tasks are there by SLA status?",
     f"SELECT task_sla_status, COUNT(*) FROM {TK} GROUP BY task_sla_status",
     {"type": "drill_down"}),
    ("F53", "Explore - Narrow a List", "Show the AR_PRINT_Shirting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_PRINT_Shirting'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F54", "Explore - Narrow a List", "Show the TESTING_MG items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'TESTING_MG'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F55", "Explore - Narrow Tasks", "Show the delayed tasks in AR_NPD_YD_SHIRTING",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' AND task_sla_status = 'Delayed'",
     {"type": "add_filter", "field": "task_status"}),
    ("F56", "Explore - Narrow Tasks", "Show the open tasks in AR_YD_Shirting",
     f"SELECT task_id, task_display_name FROM {TK} "
     "WHERE business_object_type = 'AR_YD_Shirting' AND task_status = 'open'",
     {"type": "add_filter", "field": "task_sla_status"}),
    ("F57", "Explore - Group a List", "Show the items in business unit unit1",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_unit = 'unit1'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F58", "Explore - Sort a List", "Show the AR_SALESPLAN_Suiting items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_type = 'AR_SALESPLAN_Suiting'",
     {"type": "set_sort", "field": "business_object_client_due_at"}),
    ("F59", "Explore - Drill Down", "How many items are there by business unit?",
     f"SELECT business_unit, COUNT(*) FROM {BO} GROUP BY business_unit",
     {"type": "drill_down"}),
    ("F60", "Explore - Drill Down", "How many tasks are there by department?",
     f"SELECT task_department, COUNT(*) FROM {TK} GROUP BY task_department",
     {"type": "drill_down"}),
    ("F61", "Explore - Narrow a List", "Show the black items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_color = 'Black'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F62", "Explore - Narrow a List", "Show the green items",
     f"SELECT business_object_id, business_object_ref_id FROM {BO} "
     "WHERE business_object_color = 'Green'",
     {"type": "add_filter", "field": "business_object_status"}),
    ("F63", "Explore - Narrow Tasks", "Show the tasks assigned to the sales team",
     f"SELECT task_id, task_display_name FROM {TK} WHERE assigned_role = 'sales_team'",
     {"type": "add_filter", "field": "task_status"}),
    ("F64", "Explore - Drop a Filter", "Show open delayed tasks in AR_YD_Suiting",
     f"SELECT task_id FROM {TK} WHERE business_object_type = 'AR_YD_Suiting' "
     "AND task_status = 'open' AND task_sla_status = 'Delayed'",
     {"type": "remove_filter"}),
    # Behaves as zero_or_clarify rather than sql: unit7 does not exist, so
    # returning nothing and saying so are both right, and the run showed the
    # model saying so. What the case is really asserting is that an empty
    # answer has nothing worth exploring.
    ("F65", "Explore - No Suggestion Worth Making",
     "How many items are in business unit unit7?",
     f"SELECT COUNT(*) FROM {BO} WHERE business_unit = 'unit7'",
     None),
]

# -------------------------------------------------- D/E/F. conversations ---
# (conversation_id, category, [(turn_id, question, sql, decision, followup, action)])
# sql None with followup "clarification" means the turn should ask, not answer.
CONVERSATIONS = [
    ("G01", "Mutation - Filter then Sort", [
        ("G01.1", "Show the AR_YD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting'", "new_block", None, None),
        ("G01.2", "only the active ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' "
         "AND business_object_status = 'Active'", "follow_up", None, None),
        ("G01.3", "sort those by due date",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' "
         "AND business_object_status = 'Active' "
         "ORDER BY business_object_client_due_at", "follow_up", None, None),
    ]),
    ("G02", "Mutation - Filter then Limit", [
        ("G02.1", "Show the AR_YD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting'", "new_block", None, None),
        ("G02.2", "only black ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' "
         "AND business_object_color = 'Black'", "follow_up", None, None),
        ("G02.3", "just the first 5",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' "
         "AND business_object_color = 'Black' LIMIT 5", "follow_up", None, None),
    ]),
    ("G03", "Mutation - Group then Drill Down", [
        ("G03.1", "Show the AR_NPD_YD_SHIRTING items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "new_block", None, None),
        ("G03.2", "group them by status",
         f"SELECT business_object_status, COUNT(*) FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "GROUP BY business_object_status", "follow_up", "exploration",
         {"type": "drill_down"}),
        ("G03.3", "show me the individual rows",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "follow_up", None, None),
    ]),
    ("G04", "Mutation - Remove a Filter", [
        ("G04.1", "Show active AR_NPD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting' "
         "AND business_object_status = 'Active'", "new_block", None, None),
        ("G04.2", "remove that filter",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting'", "follow_up", None, None),
        ("G04.3", "how many is that?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_NPD_Shirting'",
         "follow_up", None, None),
    ]),
    ("G05", "Mutation - Date Range", [
        ("G05.1", "How many business objects were created in May 2026?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-05-01' "
         "AND business_object_created_at < DATE '2026-06-01'", "new_block", None, None),
        ("G05.2", "what about June?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-06-01' "
         "AND business_object_created_at < DATE '2026-07-01'", "follow_up", None, None),
        ("G05.3", "and April?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_created_at >= DATE '2026-04-01' "
         "AND business_object_created_at < DATE '2026-05-01'", "follow_up", None, None),
    ]),
    ("G06", "Analytical - Compare Subjects", [
        ("G06.1", "How many delayed tasks are in AR_YD_Suiting?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_YD_Suiting' "
         "AND task_sla_status = 'Delayed'", "new_block", None, None),
        ("G06.2", "what about AR_PD_Suiting?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_PD_Suiting' "
         "AND task_sla_status = 'Delayed'", "rebase", None, None),
        ("G06.3", "and AR_NPD_Shirting?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_NPD_Shirting' "
         "AND task_sla_status = 'Delayed'", "rebase", None, None),
    ]),
    ("G07", "Analytical - Drill from Aggregate", [
        ("G07.1", "How many tasks are there by SLA status?",
         f"SELECT task_sla_status, COUNT(*) FROM {TK} GROUP BY task_sla_status",
         "new_block", "exploration", {"type": "drill_down"}),
        ("G07.2", "show me the delayed ones",
         f"SELECT task_id, task_display_name FROM {TK} WHERE task_sla_status = 'Delayed'",
         "follow_up", None, None),
        ("G07.3", "only the open ones",
         f"SELECT task_id, task_display_name FROM {TK} WHERE task_sla_status = 'Delayed' "
         "AND task_status = 'open'", "follow_up", None, None),
    ]),
    ("G08", "Analytical - Break Down then Narrow", [
        ("G08.1", "How many items are there by colour?",
         f"SELECT business_object_color, COUNT(*) FROM {BO} GROUP BY business_object_color",
         "new_block", None, None),
        ("G08.2", "only the active ones",
         f"SELECT business_object_color, COUNT(*) FROM {BO} "
         "WHERE business_object_status = 'Active' GROUP BY business_object_color",
         "follow_up", None, None),
        ("G08.3", "how many of those are black?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_status = 'Active' "
         "AND business_object_color = 'Black'", "follow_up", None, None),
    ]),
    ("G09", "New Topic - Different Entity", [
        ("G09.1", "Show delayed AR_YD_Suiting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' AND delayed_task_count > 0",
         "new_block", None, None),
        ("G09.2", "only those with more than one",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' AND delayed_task_count > 1",
         "follow_up", None, None),
        # The turn the brief describes. It must not inherit
        # business_object_type or delayed_task_count from the thread above.
        ("G09.3", "Show my open tasks",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE assigned_user_id = 1 AND task_status = 'open'", "new_block", None, None),
    ]),
    ("G10", "New Topic - Different Entity", [
        ("G10.1", "Show active AR_NPD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting' "
         "AND business_object_status = 'Active'", "new_block", None, None),
        ("G10.2", "only the black ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_Shirting' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", None, None),
        ("G10.3", "List all users",
         "SELECT user_id, user_name FROM tms_user_flat", "new_block", None, None),
    ]),
    ("G11", "Multi-step - Filter Sort Group Count", [
        ("G11.1", "Show the AR_NPD_YD_SHIRTING items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "new_block", None, None),
        ("G11.2", "only active",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active'", "follow_up", None, None),
        ("G11.3", "group them by colour",
         f"SELECT business_object_color, COUNT(*) FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active' GROUP BY business_object_color",
         "follow_up", None, None),
        ("G11.4", "show me the black ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", None, None),
        ("G11.5", "how many?",
         f"SELECT COUNT(*) FROM {BO} WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", None, None),
    ]),
    ("G12", "Multi-step - Stack then Unstack", [
        ("G12.1", "Show the AR_YD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting'", "new_block", None, None),
        ("G12.2", "only active ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' "
         "AND business_object_status = 'Active'", "follow_up", None, None),
        ("G12.3", "and only black",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' "
         "AND business_object_status = 'Active' AND business_object_color = 'Black'",
         "follow_up", None, None),
        ("G12.4", "drop the colour filter",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting' "
         "AND business_object_status = 'Active'", "follow_up", None, None),
        ("G12.5", "drop the status one too",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Shirting'", "follow_up", None, None),
    ]),
    ("G13", "Multi-step - Typo mid-thread", [
        ("G13.1", "Show the AR_PD_Shirting items",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting'", "new_block", None, None),
        ("G13.2", "only the activ ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting' "
         "AND business_object_status = 'Active'", "follow_up", None, None),
        ("G13.3", "group them by colur",
         f"SELECT business_object_color, COUNT(*) FROM {BO} "
         "WHERE business_object_type = 'AR_PD_Shirting' "
         "AND business_object_status = 'Active' GROUP BY business_object_color",
         "follow_up", None, None),
    ]),
    ("G14", "Multi-step - Ambiguity then Resolution", [
        # Asks which AR_YD type, then the user answers, and the thread carries
        # on normally from there.
        ("G14.1", "Show the AR_YD items", None, "new_block", "clarification",
         {"type": "set_entity", "value": "AR_YD_Suiting"}),
        ("G14.2", "AR_YD_Suiting",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting'", "clarification_response", None, None),
        ("G14.3", "only the closed ones",
         f"SELECT business_object_id, business_object_ref_id FROM {BO} "
         "WHERE business_object_type = 'AR_YD_Suiting' "
         "AND business_object_status = 'Closed'", "follow_up", None, None),
    ]),
    ("G15", "Multi-step - Task Thread", [
        ("G15.1", "Show the tasks in AR_NPD_YD_SHIRTING",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING'", "new_block", None, None),
        ("G15.2", "only open ones",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' AND task_status = 'open'",
         "follow_up", None, None),
        ("G15.3", "and only delayed",
         f"SELECT task_id, task_display_name FROM {TK} "
         "WHERE business_object_type = 'AR_NPD_YD_SHIRTING' AND task_status = 'open' "
         "AND task_sla_status = 'Delayed'", "follow_up", None, None),
        ("G15.4", "how many?",
         f"SELECT COUNT(*) FROM {TK} WHERE business_object_type = 'AR_NPD_YD_SHIRTING' "
         "AND task_status = 'open' AND task_sla_status = 'Delayed'",
         "follow_up", None, None),
    ]),
]


# ---------------------------------------------------------------- building --

def _state_for(sql: str) -> ConversationState:
    state = ConversationState()
    update_state(state, "", sql, 1, None, "new_block")
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    register_secrets(settings.secrets())

    from benchmark.lean_runner import load_gazetteer
    gazetteer = load_gazetteer()

    problems: list[str] = []
    questions: list[dict] = []

    def check_sql(case_id: str, sql: str, allow_zero: bool = False) -> int | None:
        """Execute the case's SQL. Returns the row count the runner will see."""
        result = run_readonly(settings, sql, settings.statement_timeout_ms)
        if result.error:
            problems.append(f"{case_id}: {result.error}")
            return None
        empty = not result.rows or (len(result.rows) == 1 and result.rows[0][0] == 0)
        if empty and not allow_zero:
            problems.append(f"{case_id}: returns nothing, so it measures nothing")
        return 0 if empty else len(result.rows)

    # -- A. repair -----------------------------------------------------------
    for case_id, category, typed, expected, sql in REPAIR:
        produced = normalize(typed).question
        if produced != expected:
            problems.append(
                f"{case_id}: repair layer produces {produced!r}, case expects {expected!r}")
        check_sql(case_id, sql)
        # Deliberately no expect_followup. A repair case is about the repair
        # and the SQL that follows it; asserting a continuation as well would
        # fail turns for a second, unrelated reason. "How many users are
        # there?" has no useful next move -- tms_user_flat has no enumerated
        # column and no business rule -- and saying nothing is the right
        # answer there, not a defect. Exploration is asserted by the 25 cases
        # built for it, where the expectation is validated against what the
        # generator can actually offer.
        questions.append({
            "id": case_id, "category": category, "question": typed,
            "expect_normalized": expected, "expected_sql": sql,
        })

    # -- B. clarification ----------------------------------------------------
    for case_id, question, must_offer in AMBIGUOUS_ENTITY:
        followup = clarify_entity(question, gazetteer)
        if followup is None:
            problems.append(f"{case_id}: {question!r} is not detected as ambiguous")
        elif must_offer not in [s.action.value for s in followup.suggestions]:
            problems.append(f"{case_id}: {must_offer} not among the offered types")
        questions.append({
            "id": case_id, "category": "Clarify - Ambiguous Entity",
            "question": question, "expected_sql": None,
            "expect_behavior": "clarify", "expect_followup": "clarification",
            "expect_action": {"type": "set_entity", "value": must_offer},
        })

    for case_id, category, question in NO_SUCH_THING:
        questions.append({
            "id": case_id, "category": category, "question": question,
            "expected_sql": None, "expect_behavior": "clarify",
            "expect_followup": "clarification",
        })

    for case_id, question, sql in UNKNOWN_VALUE:
        check_sql(case_id, sql, allow_zero=True)
        questions.append({
            "id": case_id, "category": "Clarify - Unknown Value",
            "question": question, "expected_sql": sql,
            "expect_behavior": "zero_or_clarify",
        })

    # -- C. exploration ------------------------------------------------------
    for case_id, category, question, sql, action in EXPLORATION:
        rows = check_sql(case_id, sql, allow_zero=(action is None))
        # The expectation is only fair if the generator can actually meet it,
        # and it is only honest if it is checked with the row count the runner
        # will pass -- an empty result is meant to produce no suggestions.
        offered = explore(_state_for(sql), row_count=rows)
        if action is None:
            if offered is not None:
                problems.append(f"{case_id}: expected no suggestions, got "
                                f"{[s.id for s in offered.suggestions]}")
        elif offered is None:
            problems.append(f"{case_id}: no suggestions offered at all")
        elif not any(
            all(s.action.to_dict().get(k) == v for k, v in action.items())
            for s in offered.suggestions
        ):
            problems.append(
                f"{case_id}: {action} not offered; got "
                f"{[s.action.to_dict() for s in offered.suggestions]}")
        entry = {
            "id": case_id, "category": category, "question": question,
            "expected_sql": sql,
            "expect_followup": "exploration" if action else None,
        }
        if action is None:
            # The only no-suggestion case is a no-rows case, and an honest
            # empty answer and a clarification are both correct there.
            entry["expect_behavior"] = "zero_or_clarify"
            entry.pop("expect_followup")
        if action:
            entry["expect_action"] = action
        questions.append(entry)

    # -- D/E/F. conversations ------------------------------------------------
    for conv_id, category, turns in CONVERSATIONS:
        rendered = []
        for turn_id, question, sql, decision, followup, action in turns:
            if sql is not None:
                check_sql(turn_id, sql)
            entry = {
                "id": turn_id, "question": question, "expected_sql": sql,
                "expect_decision": decision,
            }
            if sql is None:
                entry["expect_behavior"] = "clarify"
            if followup:
                entry["expect_followup"] = followup
            if action:
                entry["expect_action"] = action
            rendered.append(entry)
        questions.append({"id": conv_id, "category": category, "turns": rendered})

    turn_count = sum(len(q.get("turns", [q])) for q in questions)
    print(f"  {len(questions)} entries, {turn_count} turns")

    if problems:
        print(f"\n  {len(problems)} problem(s):")
        for problem in problems:
            print(f"    {problem}")
        return 1

    if args.dry_run:
        print("  dry run: nothing written")
        return 0

    OUT.write_text(
        "# Follow-up suite: repair, clarification, exploration and the state\n"
        "# mutations behind them. Generated and validated by\n"
        "# scripts/build_followup_suite.py -- do not edit by hand.\n"
        "#\n"
        "# expect_normalized asserts what the repair layer makes of the question\n"
        "# before anything else sees it. expect_followup and expect_action assert\n"
        "# what is offered once the turn is done. Both are scored separately from\n"
        "# the SQL, because a turn can write a perfect query and still offer a\n"
        "# useless continuation.\n"
        + yaml.safe_dump({"version": 1, "questions": questions},
                         sort_keys=False, width=100, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"  wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
