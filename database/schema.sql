-- Demo schema for the Wren + Claude Code text-to-SQL evaluation POC.
--
-- Three flat tables in a workflow/task-management domain, deliberately shaped
-- like the real system under evaluation: few tables, wide-ish rows, and two
-- distinct user relationships that are easy to confuse (workflow OWNER vs task
-- ASSIGNEE). That confusion is the point -- several benchmark questions exist
-- purely to test whether the semantic layer prevents it.
--
-- No COMMENT ON statements: knowledge configuration A is defined as the raw
-- introspected schema with no descriptions attached, so the database itself
-- must stay description-free. All semantics live in metadata/*.yaml and reach
-- the model only through Wren's MDL and instructions.

DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS workflows CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id          integer PRIMARY KEY,
    full_name   text    NOT NULL,
    email       text    NOT NULL UNIQUE,
    department  text    NOT NULL,
    role        text    NOT NULL,
    status      text    NOT NULL
);

CREATE TABLE workflows (
    id            integer PRIMARY KEY,
    name          text    NOT NULL,
    description   text,
    category      text    NOT NULL,
    status        text    NOT NULL,
    owner_user_id integer NOT NULL REFERENCES users (id),
    created_at    timestamp NOT NULL,
    updated_at    timestamp NOT NULL
);

CREATE TABLE tasks (
    id               integer PRIMARY KEY,
    workflow_id      integer NOT NULL REFERENCES workflows (id),
    name             text    NOT NULL,
    description      text,
    status           text    NOT NULL,
    priority         text    NOT NULL,
    assigned_user_id integer REFERENCES users (id),
    due_date         date,
    completed_at     timestamp,
    created_at       timestamp NOT NULL
);

CREATE INDEX idx_workflows_owner    ON workflows (owner_user_id);
CREATE INDEX idx_tasks_workflow     ON tasks (workflow_id);
CREATE INDEX idx_tasks_assignee     ON tasks (assigned_user_id);
CREATE INDEX idx_tasks_status       ON tasks (status);
CREATE INDEX idx_tasks_due_date     ON tasks (due_date);
