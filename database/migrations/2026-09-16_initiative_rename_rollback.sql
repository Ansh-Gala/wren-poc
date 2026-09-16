-- database/migrations/2026-09-16_initiative_rename_rollback.sql
-- Exact inverse of 2026-09-16_initiative_rename.sql, statements reversed.
-- Drop the compatibility views first, then undo every ALTER in reverse
-- order. Within each view, column-rename inverses use the view's current
-- (new) name and its own RENAME TO comes last for that view.

DROP VIEW IF EXISTS tms_business_object_flat;
DROP VIEW IF EXISTS tms_business_object_attributes_flat;

ALTER VIEW tms_issue_flat RENAME COLUMN is_initiative_delayed TO is_business_object_delayed;
ALTER VIEW tms_issue_flat RENAME COLUMN initiative_color     TO business_object_color;
ALTER VIEW tms_issue_flat RENAME COLUMN initiative_type      TO business_object_type;
ALTER VIEW tms_issue_flat RENAME COLUMN initiative_status    TO business_object_status;
ALTER VIEW tms_issue_flat RENAME COLUMN initiative_ref_id    TO business_object_ref_id;
ALTER VIEW tms_issue_flat RENAME COLUMN initiative_id        TO bo_id;

ALTER VIEW tms_task_flat RENAME COLUMN is_initiative_delayed TO is_business_object_delayed;
ALTER VIEW tms_task_flat RENAME COLUMN initiative_color     TO business_object_color;
ALTER VIEW tms_task_flat RENAME COLUMN initiative_type      TO business_object_type;
ALTER VIEW tms_task_flat RENAME COLUMN initiative_status    TO business_object_status;
ALTER VIEW tms_task_flat RENAME COLUMN initiative_ref_id    TO business_object_ref_id;
ALTER VIEW tms_task_flat RENAME COLUMN initiative_id        TO bo_id;

ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN initiative_id TO business_object_id;
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN attribute_initiative_type TO initiative_type;
ALTER VIEW tms_initiative_attributes_flat RENAME TO tms_business_object_attributes_flat;

ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_expected_completion_date TO business_object_expected_completion_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_end_date TO business_object_end_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_start_date TO business_object_start_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_status   TO business_object_status;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_client_due_at TO business_object_client_due_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_updated_at TO business_object_updated_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_created_at TO business_object_created_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_note     TO business_object_note;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_color    TO business_object_color;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_type     TO business_object_type;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_ref_id   TO business_object_ref_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_id       TO business_object_id;
ALTER VIEW tms_initiative_flat RENAME TO tms_business_object_flat;
