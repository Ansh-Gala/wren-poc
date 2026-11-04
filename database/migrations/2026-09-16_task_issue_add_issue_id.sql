-- tms_task_issue_flat gains the issue's own id, 2026-09-16.
--
-- The source groups by issue.id but never selected it, so no row could be
-- told from another -- issues 1 to 4 are all titled 'test isue' on task 278 --
-- and nothing could link to /view-issue/<id>. It is added as the first column.
--
-- DROP then CREATE rather than CREATE OR REPLACE: a replacement may only
-- append columns, and the id belongs at the front. Grants are discarded by
-- the drop and reissued below.

DROP VIEW IF EXISTS tms_task_issue_flat;

CREATE VIEW tms_task_issue_flat AS
SELECT
    issue.id AS issue_id,
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
