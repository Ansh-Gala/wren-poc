-- database/migrations/2026-09-16_initiative_rename.sql
-- Views only. No Drupal table (vf_*) is touched, and no data moves.
-- ALTER VIEW preserves grants; the compatibility views at the foot are new
-- objects and so need their own GRANT.

ALTER VIEW tms_business_object_flat RENAME TO tms_initiative_flat;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_id       TO initiative_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_ref_id   TO initiative_ref_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_type     TO initiative_type;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_color    TO initiative_color;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_note     TO initiative_note;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_created_at TO initiative_created_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_updated_at TO initiative_updated_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_client_due_at TO initiative_client_due_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_status   TO initiative_status;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_start_date TO initiative_start_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_end_date TO initiative_end_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN business_object_expected_completion_date TO initiative_expected_completion_date;
-- business_unit is deliberately absent. It is a different entity.

ALTER VIEW tms_business_object_attributes_flat RENAME TO tms_initiative_attributes_flat;
-- The JSON attribute moves first so it is out of the way; see the collision note.
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN initiative_type TO attribute_initiative_type;
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN business_object_id TO initiative_id;

ALTER VIEW tms_task_flat RENAME COLUMN bo_id                     TO initiative_id;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_ref_id    TO initiative_ref_id;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_status    TO initiative_status;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_type      TO initiative_type;
ALTER VIEW tms_task_flat RENAME COLUMN business_object_color     TO initiative_color;
ALTER VIEW tms_task_flat RENAME COLUMN is_business_object_delayed TO is_initiative_delayed;

ALTER VIEW tms_issue_flat RENAME COLUMN bo_id                     TO initiative_id;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_ref_id    TO initiative_ref_id;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_status    TO initiative_status;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_type      TO initiative_type;
ALTER VIEW tms_issue_flat RENAME COLUMN business_object_color     TO initiative_color;
ALTER VIEW tms_issue_flat RENAME COLUMN is_business_object_delayed TO is_initiative_delayed;

-- Compatibility: the old names stay readable until Task 9 converts the last
-- suite. Dropped in Task 10. Column order matches the pre-migration views.
CREATE OR REPLACE VIEW tms_business_object_flat AS
  SELECT initiative_id                        AS business_object_id,
         initiative_ref_id                    AS business_object_ref_id,
         business_unit,
         initiative_type                      AS business_object_type,
         initiative_color                     AS business_object_color,
         initiative_note                      AS business_object_note,
         initiative_created_at                AS business_object_created_at,
         initiative_updated_at                AS business_object_updated_at,
         initiative_client_due_at             AS business_object_client_due_at,
         common_buffer, buff_penetration_prcnt, buff_penetration_days,
         total_remaining_duration, days_to_due_date, hold_days,
         workflow_id, workflow_code, workflow_name,
         initiative_status                    AS business_object_status,
         initiative_start_date                AS business_object_start_date,
         initiative_end_date                  AS business_object_end_date,
         elapsed_days,
         initiative_expected_completion_date  AS business_object_expected_completion_date,
         short_closed_by, short_closed_on,
         current_active_milestone, current_milestone_delay_days,
         current_milestone_expected_completion,
         total_task_count, open_task_count, closed_task_count,
         delayed_task_count, open_tasks_list
  FROM tms_initiative_flat;
GRANT SELECT ON tms_business_object_flat TO wren_ro;

CREATE OR REPLACE VIEW tms_business_object_attributes_flat AS
  SELECT initiative_id             AS business_object_id,
         attribute_initiative_type AS initiative_type,
         category, end_date, season, program, request_receipt_date, pi_date,
         stage, data_color, brandix_t_a, csbd_date, batch_no, item_code,
         volume, event, channel, vendor, total_qty, moq, number_of_options,
         count, merchant_name, person, assign_date, quality, buyer,
         mcode_won_number, ex_mill_date, garment_desc, matching_instruction,
         fabric_description, dye_part, shade, internal_or_confirmed,
         division, style_or_garment_code
  FROM tms_initiative_attributes_flat;
GRANT SELECT ON tms_business_object_attributes_flat TO wren_ro;
