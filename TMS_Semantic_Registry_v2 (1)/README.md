# TMS Semantic Registry v2.1

Learning material for an AI agent / semantic registry that generates read-only SQL
for TMS.

Verified against database `arvind_retail_chatbot_test_1` on 2026-09-05. Every table
and column named in this package was read from `information_schema`.

## Core tables

Six flat views exist in the current database:

1. `tms_task_flat` (3354 rows)
2. `tms_business_object_flat` (307 rows)
3. `tms_business_object_attributes_flat` (307 rows)
4. `tms_user_flat` (63 rows)
5. `tms_user_department_flat` (160 rows)
6. `tms_role_flat` (21 rows)

## Changes from v2.0

v2.0 described the pre-flattening source columns rather than the flat views, so most
of its `tms_task_flat` and `tms_user_flat` entries named columns that do not exist.

- `tms_task_flat` — 22 of 28 documented columns did not exist and 31 real columns were
  undocumented. Replaced with the real 37.
- `tms_user_flat` — documented `entity_id`, `bundle`, `field_full_name_value`; the real
  columns are `user_id`, `user_name`, `role_count`, `department_count`.
- `tms_business_object_flat` — `open_task_list` corrected to `open_tasks_list`.
- `tms_role_flat` — added the missing `department_path`.
- `tms_business_object_attributes_flat` and `tms_user_department_flat` — v2.0 omitted
  both. The first was described as a planned future extension; it is a real view with
  307 rows.
- Column-name corrections propagated through the rules, glossary, synonyms and
  examples: `assigned_uid` → `assigned_user_id`, `status` → `task_status`,
  `buffer_hrs` → `task_sla_hours`, `task_start_date` → `task_start_at`,
  `closed_on` → `task_closed_at`, `next_followup` → `next_followup_at`,
  `tkt_code` → `task_code`.

## Critical semantic rule

Business Object, BO, Initiative, and Order are synonyms for the same TMS entity.

## Schema rule

Do not invent columns. The registry describes only columns confirmed present in the
six flat views.

## Time

Date/time columns in the flat views are PostgreSQL `timestamptz`, already converted
from the source epoch integers. Use them directly. v2.0's statement that source values
are Unix epoch is true of the underlying tables but not of these views.

Date-like attributes in `tms_business_object_attributes_flat` are stored as `text` and
need an explicit cast.

## Already-derived columns

The views precompute values the rules previously asked to be recalculated. Prefer
`task_sla_status`, `is_delayed_open_task`, `is_delayed_closed_task`,
`task_elapsed_hours`, `task_elapsed_days`, `is_open_task`, `is_closed_task`,
`is_not_started_task` and `is_followup` over rebuilding the logic.

Likewise `business_object_status` and `business_object_color` are already resolved to
text (`Active` / `Closed` / `Short Closed`, and `Black` / `Green` / `White` / `Red`).
The source codes 1/2/80 and a_bl/b_re/c_ye/d_gr do not appear in the views.

## Client-specific attributes

`tms_business_object_attributes_flat` holds one column per registered attribute and
must not be treated as universal TMS columns — attributes differ by client.

Coverage in this database is uneven: `quality` is NULL for all 307 rows and `season`
is populated for only 16. Confirm an attribute has data before filtering on it.
