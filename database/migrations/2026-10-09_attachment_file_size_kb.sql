-- tms_attachment_flat.file_size in KB, 2026-10-09.
--
-- The files are 2 KB to 95 KB, so bytes were hard to read. KB is 1024 bytes,
-- rounded to 2 decimal places. max_file_size, the tag's limit, stays in bytes.
--
-- DROP then CREATE rather than CREATE OR REPLACE: a replacement cannot change
-- a column's type (bigint to numeric). Grants are discarded by the drop and
-- reissued below. The Drupal module does the same in update 9012.

DROP VIEW IF EXISTS tms_attachment_flat;

CREATE VIEW tms_attachment_flat AS
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
    ROUND(file.filesize / 1024.0, 2) AS file_size,

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
