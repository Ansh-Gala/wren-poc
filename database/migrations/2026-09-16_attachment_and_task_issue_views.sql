-- Two new flat views, 2026-09-16.
--
-- tms_attachment_flat   : files attached to an initiative or task, with the
--                         tag that classifies them.
-- tms_task_issue_flat   : issues raised against a task, with their comment
--                         counts and latest comment.
--
-- Source SQL is the human partner's, from
-- Desktop/Vector/Flat Table Structure/sql/. One alias changed by their
-- instruction: tag.bo_type is exposed as initiative_name.

CREATE OR REPLACE VIEW tms_attachment_flat AS
SELECT
    -- Relationships
    attachment.bo_id AS initiative_id,
    attachment.task_id,

    -- Tag details
    tag.tag_name,
    tag.tag_desc,
    tag.folder_path,
    tag.task_names,
    tag.extensions,
    tag.max_file_size,
    tag.bo_type AS initiative_name,
    tag.sequence,

    -- File details
    file.filename AS file_name,
    file.uri AS file_uri,
    file.filesize AS file_size,

    -- Attachment details
    attachment.entity_type,
    attachment.entity_id,
    attachment.status,
    TO_TIMESTAMP(attachment.created) AS attachment_created_at,
    attachment.created_by AS attachment_created_by_user_id

FROM vf_bo_attachment attachment

LEFT JOIN vf_bo_attachment_tagging tag
    ON tag.tag_id = attachment.tag_id

LEFT JOIN vf_file_managed file
    ON file.fid = attachment.f_id

WHERE (attachment.entity_type IS NULL OR attachment.entity_type = '')
  AND attachment.status = 'active';
GRANT SELECT ON tms_attachment_flat TO wren_ro;

CREATE OR REPLACE VIEW tms_task_issue_flat AS
SELECT
    issue.entity_id AS task_id,
    issue.title AS issue_title,
    issue.issue_description,

    role_department.sub_department AS issue_sub_department,
    category.master_json ->> 'category' AS issue_category_name,

    issue.status AS issue_status,
    issue.hold_days AS issue_hold_days,

    issue.assigned_uid AS issue_assigned_user_id,
    issue.resolved_by AS issue_resolved_by_user_id,
    issue.closed_by AS issue_closed_by_user_id,
    issue.created_by AS issue_created_by_user_id,
    issue.updated_by AS issue_updated_by_user_id,

    TO_TIMESTAMP(issue.created) AS issue_created_at,
    TO_TIMESTAMP(issue.updated) AS issue_updated_at,
    TO_TIMESTAMP(issue.resolved_on) AS issue_resolved_at,
    TO_TIMESTAMP(issue.closed_on) AS issue_closed_at,

    COUNT(comment.id) AS comment_count,
    (ARRAY_AGG(comment.comment ORDER BY comment.created DESC))[1] AS last_comment,
    TO_TIMESTAMP(MAX(comment.created)) AS last_comment_at

FROM vf_issue_flow issue

LEFT JOIN vf_role_department_list role_department
    ON role_department.role = issue.department

LEFT JOIN vf_master_data_issue_category category
    ON category.id = issue.category_id

LEFT JOIN vf_issue_comment comment
    ON comment.issue_id = issue.id

WHERE issue.entity_type = 'task'

GROUP BY
    issue.id,
    issue.entity_id,
    issue.title,
    issue.issue_description,
    role_department.sub_department,
    issue.category_id,
    category.master_json ->> 'category',
    issue.status,
    issue.hold_days,
    issue.assigned_uid,
    issue.resolved_by,
    issue.closed_by,
    issue.created_by,
    issue.updated_by,
    issue.created,
    issue.updated,
    issue.resolved_on,
    issue.closed_on;
GRANT SELECT ON tms_task_issue_flat TO wren_ro;
