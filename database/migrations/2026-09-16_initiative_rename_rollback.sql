-- Rollback of the 2026-09-16 Initiative rename. Exact inverse.
DROP VIEW IF EXISTS tms_business_object_flat;
DROP VIEW IF EXISTS tms_business_object_attributes_flat;

DROP VIEW IF EXISTS tms_task_flat CASCADE;
-- CURRENT definition of tms_task_flat, pre-migration.
-- Apply the column renames to the OUTPUT ALIASES only, then append the
-- six trailing compatibility columns.
CREATE OR REPLACE VIEW tms_task_flat AS
 SELECT task.task_id,
    task.tkt_code AS task_code,
    task.task_name AS task_machine_code,
    task.task_display_name,
    task.status AS task_status,
        CASE
            WHEN NULLIF(task.task_start_date::text, ''::text)::bigint::numeric > EXTRACT(epoch FROM CURRENT_TIMESTAMP) AND lower(task.status::text) <> 'closed'::text THEN 'Not Started'::character varying
            WHEN lower(task.status::text) = 'open'::text THEN 'Open'::character varying
            WHEN lower(task.status::text) = 'closed'::text THEN 'Closed'::character varying
            ELSE task.status
        END AS task_display_status,
        CASE
            WHEN lower(task.status::text) = 'open'::text AND NULLIF(task.task_start_date::text, ''::text)::bigint::numeric <= EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN true
            ELSE false
        END AS is_open_task,
        CASE
            WHEN lower(task.status::text) = 'closed'::text THEN true
            ELSE false
        END AS is_closed_task,
        CASE
            WHEN NULLIF(task.task_start_date::text, ''::text)::bigint::numeric > EXTRACT(epoch FROM CURRENT_TIMESTAMP) AND lower(task.status::text) <> 'closed'::text THEN true
            ELSE false
        END AS is_not_started_task,
    task.display_flag,
    task.instant_closer,
    task.reopen_count,
    task.assigned_uid AS assigned_user_id,
    assigned_user.field_full_name_value AS assigned_user_name,
    task.assigned_role,
    task.sub_department AS task_sub_department,
    role_department.department AS task_department,
    to_timestamp(NULLIF(task.created::text, ''::text)::bigint::double precision) AS created_at,
    to_timestamp(NULLIF(task.task_start_date::text, ''::text)::bigint::double precision) AS task_start_at,
        CASE
            WHEN NULLIF(task.assigned_on::text, ''::text)::bigint > 0 THEN to_timestamp(NULLIF(task.assigned_on::text, ''::text)::bigint::double precision)
            ELSE NULL::timestamp with time zone
        END AS task_assigned_at,
        CASE
            WHEN NULLIF(task.closed_on::text, ''::text) IS NOT NULL AND NULLIF(task.closed_on::text, ''::text)::bigint > 0 THEN to_timestamp(NULLIF(task.closed_on::text, ''::text)::bigint::double precision)
            ELSE NULL::timestamp with time zone
        END AS task_closed_at,
        CASE
            WHEN NULLIF(task.reopen_date::text, ''::text) IS NOT NULL AND NULLIF(task.reopen_date::text, ''::text)::bigint > 0 THEN to_timestamp(NULLIF(task.reopen_date::text, ''::text)::bigint::double precision)
            ELSE NULL::timestamp with time zone
        END AS task_reopen_at,
        CASE
            WHEN NULLIF(task.next_followup::text, ''::text) IS NOT NULL AND NULLIF(task.next_followup::text, ''::text)::bigint > 0 THEN to_timestamp(NULLIF(task.next_followup::text, ''::text)::bigint::double precision)
            ELSE NULL::timestamp with time zone
        END AS next_followup_at,
        CASE
            WHEN NULLIF(task.next_followup::text, ''::text)::bigint::numeric > EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN true
            ELSE false
        END AS is_followup,
    task.buffer_hrs AS task_sla_hours,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND NULLIF(task.closed_on::text, ''::text) IS NOT NULL AND NULLIF(task.task_start_date::text, ''::text) IS NOT NULL THEN (NULLIF(task.closed_on::text, ''::text)::bigint - NULLIF(task.task_start_date::text, ''::text)::bigint)::numeric / 3600.0
            WHEN lower(task.status::text) = 'open'::text AND NULLIF(task.task_start_date::text, ''::text)::bigint::numeric <= EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN (EXTRACT(epoch FROM CURRENT_TIMESTAMP) - NULLIF(task.task_start_date::text, ''::text)::bigint::numeric) / 3600.0
            ELSE NULL::numeric
        END AS task_elapsed_hours,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND NULLIF(task.closed_on::text, ''::text) IS NOT NULL AND NULLIF(task.task_start_date::text, ''::text) IS NOT NULL THEN date_part('day'::text, to_timestamp(NULLIF(task.closed_on::text, ''::text)::bigint::double precision) - to_timestamp(NULLIF(task.task_start_date::text, ''::text)::bigint::double precision))
            WHEN lower(task.status::text) = 'open'::text AND NULLIF(task.task_start_date::text, ''::text)::bigint::numeric <= EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN date_part('day'::text, CURRENT_TIMESTAMP - to_timestamp(NULLIF(task.task_start_date::text, ''::text)::bigint::double precision))
            ELSE NULL::double precision
        END AS task_elapsed_days,
        CASE
            WHEN
            CASE
                WHEN lower(task.status::text) = 'open'::text AND NULLIF(task.task_start_date::text, ''::text)::bigint::numeric <= EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN (EXTRACT(epoch FROM CURRENT_TIMESTAMP) - NULLIF(task.task_start_date::text, ''::text)::bigint::numeric) / 3600.0
                ELSE NULL::numeric
            END::double precision > task.buffer_hrs THEN 'Yes'::text
            ELSE 'Not Applicable'::text
        END AS is_delayed_open_task,
        CASE
            WHEN
            CASE
                WHEN lower(task.status::text) = 'closed'::text THEN (NULLIF(task.closed_on::text, ''::text)::bigint - NULLIF(task.task_start_date::text, ''::text)::bigint)::numeric / 3600.0
                ELSE NULL::numeric
            END::double precision > task.buffer_hrs THEN 'Yes'::text
            ELSE 'Not Applicable'::text
        END AS is_delayed_closed_task,
        CASE
            WHEN
            CASE
                WHEN lower(task.status::text) = 'closed'::text THEN (NULLIF(task.closed_on::text, ''::text)::bigint - NULLIF(task.task_start_date::text, ''::text)::bigint)::numeric / 3600.0
                WHEN lower(task.status::text) = 'open'::text AND NULLIF(task.task_start_date::text, ''::text)::bigint::numeric <= EXTRACT(epoch FROM CURRENT_TIMESTAMP) THEN (EXTRACT(epoch FROM CURRENT_TIMESTAMP) - NULLIF(task.task_start_date::text, ''::text)::bigint::numeric) / 3600.0
                ELSE NULL::numeric
            END::double precision > task.buffer_hrs THEN 'Delayed'::text
            ELSE 'On Time'::text
        END AS task_sla_status,
    task.bo_id,
    bo.ref_id AS business_object_ref_id,
    bo.business_unit,
        CASE
            WHEN process.process_status = 1 THEN 'Active'::text
            WHEN process.process_status = 2 THEN 'Closed'::text
            WHEN process.process_status = 40 THEN 'Hold'::text
            WHEN process.process_status = 80 THEN 'Short Closed'::text
            ELSE process.process_status::text
        END AS business_object_status,
    bo.bo_type AS business_object_type,
    bo.bo_color AS business_object_color,
        CASE
            WHEN bo.bo_color::text = 'a_bl'::text THEN 'Yes'::text
            ELSE 'No'::text
        END AS is_business_object_delayed
   FROM vf_task task
     LEFT JOIN vf_business_object bo ON bo.bo_id = task.bo_id
     LEFT JOIN vf_user__field_full_name assigned_user ON assigned_user.entity_id = task.assigned_uid AND assigned_user.bundle::text = 'user'::text
     LEFT JOIN vf_role_department_list role_department ON role_department.sub_department::text = task.sub_department::text
     LEFT JOIN vf_bo_wf_mapping bo_wf_mapping ON bo_wf_mapping.bo_id = task.bo_id
     LEFT JOIN vf_process process ON process.bo_wf_mapping_id = bo_wf_mapping.id;
GRANT SELECT ON tms_task_flat TO wren_ro;
GRANT SELECT ON tms_task_flat TO wren_sdd;

DROP VIEW IF EXISTS tms_issue_flat CASCADE;
-- CURRENT definition of tms_issue_flat, pre-migration.
-- Apply the column renames to the OUTPUT ALIASES only, then append the
-- six trailing compatibility columns.
CREATE OR REPLACE VIEW tms_issue_flat AS
 SELECT issue.id AS issue_id,
    issue.title AS issue_title,
    issue.issue_description,
    issue.department AS issue_department,
    issue.category_id AS issue_category_id,
    issue.status AS issue_status,
    issue.hold_days AS issue_hold_days,
    issue.assigned_uid AS issue_assigned_user_id,
    issue_assigned_user.user_name AS issue_assigned_user_name,
    issue_assigned_user.department AS issue_assigned_user_department,
    issue_resolved_user.user_name AS issue_resolved_by_name,
    issue_resolved_user.department AS issue_resolved_by_department,
    issue_closed_user.user_name AS issue_closed_by_name,
    issue_closed_user.department AS issue_closed_by_department,
    issue_created_user.user_name AS issue_created_by_name,
    issue_created_user.department AS issue_created_by_department,
    issue_updated_user.user_name AS issue_updated_by_name,
    issue_updated_user.department AS issue_updated_by_department,
        CASE
            WHEN NULLIF(issue.created::text, ''::text) IS NOT NULL AND issue.created > 0 THEN to_char((to_timestamp(issue.created::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS issue_created_at,
        CASE
            WHEN NULLIF(issue.updated::text, ''::text) IS NOT NULL AND issue.updated > 0 THEN to_char((to_timestamp(issue.updated::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS issue_updated_at,
        CASE
            WHEN NULLIF(issue.resolved_on::text, ''::text) IS NOT NULL AND issue.resolved_on > 0 THEN to_char((to_timestamp(issue.resolved_on::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS issue_resolved_at,
        CASE
            WHEN NULLIF(issue.closed_on::text, ''::text) IS NOT NULL AND issue.closed_on > 0 THEN to_char((to_timestamp(issue.closed_on::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS issue_closed_at,
    COALESCE(comments.comment_count, 0::bigint) AS comment_count,
    comments.last_comment,
        CASE
            WHEN comments.last_comment_at IS NOT NULL THEN to_char((to_timestamp(comments.last_comment_at::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS last_comment_at,
    task.task_id,
    task.tkt_code AS task_code,
    task.task_name AS task_machine_code,
    task.status AS task_status,
    task.assigned_uid AS task_assigned_user_id,
    task_assigned_user.user_name AS task_assigned_user_name,
    task.assigned_role AS task_assigned_role,
    task.sub_department AS task_sub_department,
    task_role_department.department AS task_department,
        CASE
            WHEN NULLIF(task.created::text, ''::text) IS NOT NULL AND task.created::bigint > 0 THEN to_char((to_timestamp(task.created::bigint::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS task_created_at,
        CASE
            WHEN NULLIF(task.task_start_date::text, ''::text) IS NOT NULL AND task.task_start_date::bigint > 0 THEN to_char((to_timestamp(task.task_start_date::bigint::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS task_start_at,
        CASE
            WHEN NULLIF(task.assigned_on::text, ''::text) IS NOT NULL AND task.assigned_on::bigint > 0 THEN to_char((to_timestamp(task.assigned_on::bigint::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS task_assigned_at,
        CASE
            WHEN NULLIF(task.closed_on::text, ''::text) IS NOT NULL AND task.closed_on::bigint > 0 THEN to_char((to_timestamp(task.closed_on::bigint::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS task_closed_at,
        CASE
            WHEN NULLIF(task.reopen_date::text, ''::text) IS NOT NULL AND task.reopen_date::bigint > 0 THEN to_char((to_timestamp(task.reopen_date::bigint::double precision) AT TIME ZONE 'Asia/Kolkata'::text), 'YYYY-MM-DD HH24:MI:SS.MS'::text) || ' +0530'::text
            ELSE NULL::text
        END AS task_reopen_at,
    task.buffer_hrs AS task_sla_hours,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND task.closed_on::bigint > 0 AND task.task_start_date::bigint > 0 THEN (task.closed_on::bigint - task.task_start_date::bigint)::numeric / 3600.0
            ELSE NULL::numeric
        END AS task_elapsed_hours,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND task.closed_on::bigint > 0 AND task.task_start_date::bigint > 0 THEN date_part('day'::text, to_timestamp(task.closed_on::bigint::double precision) - to_timestamp(task.task_start_date::bigint::double precision))
            ELSE NULL::double precision
        END AS task_elapsed_days,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND task.closed_on::bigint > 0 AND task.task_start_date::bigint > 0 AND ((task.closed_on::bigint - task.task_start_date::bigint)::numeric / 3600.0)::double precision > task.buffer_hrs THEN 'Yes'::text
            ELSE 'Not Applicable'::text
        END AS is_delayed_closed_task,
        CASE
            WHEN lower(task.status::text) = 'closed'::text AND task.closed_on::bigint > 0 AND task.task_start_date::bigint > 0 AND ((task.closed_on::bigint - task.task_start_date::bigint)::numeric / 3600.0)::double precision > task.buffer_hrs THEN 'Delayed'::text
            ELSE 'On Time'::text
        END AS task_sla_status,
    task.bo_id,
    bo.ref_id AS business_object_ref_id,
    bo.business_unit,
    bo.bo_status AS business_object_status,
    bo.bo_type AS business_object_type,
    bo.bo_color AS business_object_color,
        CASE
            WHEN bo.bo_color::text = 'a_bl'::text THEN 'Yes'::text
            ELSE 'No'::text
        END AS is_business_object_delayed
   FROM vf_issue_flow issue
     LEFT JOIN vf_task task ON issue.entity_type::text = 'task'::text AND issue.entity_id = task.task_id
     LEFT JOIN vf_business_object bo ON bo.bo_id = task.bo_id
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name,
            string_agg(DISTINCT rd.department::text, ', '::text ORDER BY (rd.department::text)) AS department
           FROM vf_user__field_full_name u
             LEFT JOIN vf_user__roles ur ON ur.entity_id = u.entity_id AND ur.bundle::text = 'user'::text
             LEFT JOIN vf_role_department_list rd ON rd.role::text = ur.roles_target_id::text
          WHERE u.bundle::text = 'user'::text
          GROUP BY u.entity_id, u.field_full_name_value) issue_assigned_user ON issue_assigned_user.user_id = issue.assigned_uid
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name,
            string_agg(DISTINCT rd.department::text, ', '::text ORDER BY (rd.department::text)) AS department
           FROM vf_user__field_full_name u
             LEFT JOIN vf_user__roles ur ON ur.entity_id = u.entity_id AND ur.bundle::text = 'user'::text
             LEFT JOIN vf_role_department_list rd ON rd.role::text = ur.roles_target_id::text
          WHERE u.bundle::text = 'user'::text
          GROUP BY u.entity_id, u.field_full_name_value) issue_resolved_user ON issue_resolved_user.user_id = issue.resolved_by
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name,
            string_agg(DISTINCT rd.department::text, ', '::text ORDER BY (rd.department::text)) AS department
           FROM vf_user__field_full_name u
             LEFT JOIN vf_user__roles ur ON ur.entity_id = u.entity_id AND ur.bundle::text = 'user'::text
             LEFT JOIN vf_role_department_list rd ON rd.role::text = ur.roles_target_id::text
          WHERE u.bundle::text = 'user'::text
          GROUP BY u.entity_id, u.field_full_name_value) issue_closed_user ON issue_closed_user.user_id = issue.closed_by
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name,
            string_agg(DISTINCT rd.department::text, ', '::text ORDER BY (rd.department::text)) AS department
           FROM vf_user__field_full_name u
             LEFT JOIN vf_user__roles ur ON ur.entity_id = u.entity_id AND ur.bundle::text = 'user'::text
             LEFT JOIN vf_role_department_list rd ON rd.role::text = ur.roles_target_id::text
          WHERE u.bundle::text = 'user'::text
          GROUP BY u.entity_id, u.field_full_name_value) issue_created_user ON issue_created_user.user_id = issue.created_by
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name,
            string_agg(DISTINCT rd.department::text, ', '::text ORDER BY (rd.department::text)) AS department
           FROM vf_user__field_full_name u
             LEFT JOIN vf_user__roles ur ON ur.entity_id = u.entity_id AND ur.bundle::text = 'user'::text
             LEFT JOIN vf_role_department_list rd ON rd.role::text = ur.roles_target_id::text
          WHERE u.bundle::text = 'user'::text
          GROUP BY u.entity_id, u.field_full_name_value) issue_updated_user ON issue_updated_user.user_id = issue.updated_by
     LEFT JOIN ( SELECT u.entity_id AS user_id,
            u.field_full_name_value AS user_name
           FROM vf_user__field_full_name u
          WHERE u.bundle::text = 'user'::text) task_assigned_user ON task_assigned_user.user_id = task.assigned_uid
     LEFT JOIN vf_role_department_list task_role_department ON task_role_department.sub_department::text = task.sub_department::text
     LEFT JOIN ( SELECT ic.issue_id,
            count(*) AS comment_count,
            (array_agg(ic.comment ORDER BY ic.created DESC))[1] AS last_comment,
            max(NULLIF(ic.created::text, ''::text)::bigint) AS last_comment_at
           FROM vf_issue_comment ic
          GROUP BY ic.issue_id) comments ON comments.issue_id = issue.id
  WHERE issue.entity_type::text = 'task'::text;
GRANT SELECT ON tms_issue_flat TO wren_ro;
GRANT SELECT ON tms_issue_flat TO wren_sdd;

ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN initiative_id TO business_object_id;
ALTER VIEW tms_initiative_attributes_flat RENAME COLUMN attribute_initiative_type TO initiative_type;
ALTER VIEW tms_initiative_attributes_flat RENAME TO tms_business_object_attributes_flat;

ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_expected_completion_date TO business_object_expected_completion_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_end_date TO business_object_end_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_start_date TO business_object_start_date;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_status TO business_object_status;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_client_due_at TO business_object_client_due_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_updated_at TO business_object_updated_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_created_at TO business_object_created_at;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_note TO business_object_note;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_color TO business_object_color;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_type TO business_object_type;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_ref_id TO business_object_ref_id;
ALTER VIEW tms_initiative_flat RENAME COLUMN initiative_id TO business_object_id;
ALTER VIEW tms_initiative_flat RENAME TO tms_business_object_flat;