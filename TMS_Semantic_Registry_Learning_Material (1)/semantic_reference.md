# TMS Semantic Reference

## Canonical terms

| User language | Canonical concept | Table |
|---|---|---|
| Initiative / Order / BO / Business Object | Business Object | `tms_business_object_flat` |
| Task / Work Item / Ticket | Task | `tms_task_flat` |
| User / Employee | User | `tms_user_flat` |
| Role | Role | `tms_role_flat` |

## Key relationships

`Business Object 1 -> many Tasks`

`tms_task_flat.bo_id -> tms_business_object_flat.bo_id`

`Task -> assigned User`

`tms_task_flat.assigned_user_id -> tms_user_flat.user_id`

`Task -> Role`

`tms_task_flat.assigned_role -> tms_role_flat.role`

## Status mapping

- `1` = Active
- `2` = Closed
- `80` = Short Closed

## Core business concepts

- **My Tasks:** tasks assigned to the authenticated user and meeting TMS task-list eligibility.
- **Other Tasks:** eligible departmental/sub-department task-pool tasks; not merely tasks not assigned to the user.
- **Delayed Task:** elapsed task duration exceeds configured SLA/buffer.
- **Not Started:** task start time is in the future.
- **Current Ticket:** current task rather than follow-up.
- **Follow-up Ticket:** future follow-up occurrence.
- **Overdue Business Object:** applicable due date has passed and the Business Object is not completed/closed.

## AI query rules

1. Resolve synonyms before SQL generation.
2. Prefer flat semantic tables.
3. Use derived semantic fields such as `is_delayed` and `is_not_started`.
4. Use `COUNT(DISTINCT bo_id)` when counting Business Objects from task data.
5. Use authenticated session context for "my" questions.
6. Never modify data.
7. Do not invent missing business definitions.
