"""Schema and seed-data invariants.

These are not decorative. Several benchmark categories are only meaningful if
the data actually contains the shape they ask about -- a "workflows with no
tasks" question against a dataset where every workflow has tasks would pass
trivially and measure nothing.
"""

import pytest

from database.connection import run_readonly

pytestmark = pytest.mark.integration


def scalar(settings, sql):
    r = run_readonly(settings, sql, 10000)
    assert r.error is None, f"{sql}\n{r.error}"
    return r.rows[0][0]


def test_row_counts(settings):
    assert scalar(settings, "SELECT count(*) FROM users") == 15
    assert scalar(settings, "SELECT count(*) FROM workflows") == 8
    assert scalar(settings, "SELECT count(*) FROM tasks") == 50


def test_foreign_keys_present(settings):
    # pg_constraint, not information_schema: the latter only shows constraints
    # the current role holds privileges on, and the benchmark role has SELECT
    # only, so it would report zero even though the keys exist.
    r = run_readonly(settings, """
        SELECT conname FROM pg_constraint WHERE contype = 'f' ORDER BY conname
    """, 10000)
    assert r.error is None, r.error
    assert [row[0] for row in r.rows] == [
        "tasks_assigned_user_id_fkey",
        "tasks_workflow_id_fkey",
        "workflows_owner_user_id_fkey",
    ]


def test_no_column_comments_so_config_a_is_a_true_baseline(settings):
    """Config A must be schema-only; a COMMENT ON would leak a description."""
    assert scalar(settings, """
        SELECT count(*) FROM pg_description d
        JOIN pg_class c ON c.oid = d.objoid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
    """) == 0


@pytest.mark.parametrize(
    "label,sql,expected",
    [
        ("inactive users", "SELECT count(*) FROM users WHERE status='INACTIVE'", 3),
        ("active users", "SELECT count(*) FROM users WHERE status='ACTIVE'", 12),
        ("completed tasks", "SELECT count(*) FROM tasks WHERE status='COMPLETED'", 18),
        ("blocked tasks", "SELECT count(*) FROM tasks WHERE status='BLOCKED'", 7),
        ("in-progress tasks", "SELECT count(*) FROM tasks WHERE status='IN_PROGRESS'", 9),
        ("todo tasks", "SELECT count(*) FROM tasks WHERE status='TODO'", 16),
        ("unassigned tasks", "SELECT count(*) FROM tasks WHERE assigned_user_id IS NULL", 1),
        ("null completed_at", "SELECT count(*) FROM tasks WHERE completed_at IS NULL", 32),
    ],
)
def test_exact_status_distribution(settings, label, sql, expected):
    assert scalar(settings, sql) == expected, label


def test_completion_timestamp_is_consistent_with_status(settings):
    """completed_at is non-NULL exactly when status = 'COMPLETED'."""
    assert scalar(settings, """
        SELECT count(*) FROM tasks
        WHERE (status = 'COMPLETED') <> (completed_at IS NOT NULL)
    """) == 0


def test_date_dependent_shapes_are_non_empty(settings):
    """Category L needs these to be non-vacuous on any day of any month."""
    assert scalar(settings, """
        SELECT count(*) FROM tasks
        WHERE due_date < CURRENT_DATE AND status <> 'COMPLETED'
    """) == 10
    assert scalar(settings, """
        SELECT count(*) FROM tasks
        WHERE due_date = CURRENT_DATE AND status <> 'COMPLETED'
    """) == 3
    assert scalar(settings, """
        SELECT count(*) FROM tasks
        WHERE due_date > CURRENT_DATE AND status <> 'COMPLETED'
    """) == 19
    assert scalar(settings, """
        SELECT count(*) FROM tasks
        WHERE completed_at >= date_trunc('month', CURRENT_DATE)
          AND completed_at < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month'
    """) == 11
    assert scalar(settings, """
        SELECT count(*) FROM workflows
        WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
    """) == 3


def test_structural_coverage(settings):
    assert scalar(settings, """
        SELECT count(*) FROM workflows w
        WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.workflow_id = w.id)
    """) == 2, "workflows with zero tasks"
    assert scalar(settings, """
        SELECT count(*) FROM users u
        WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.assigned_user_id = u.id)
    """) == 3, "users with zero assigned tasks"
    assert scalar(settings, """
        SELECT count(*) FROM users u
        WHERE NOT EXISTS (SELECT 1 FROM workflows w WHERE w.owner_user_id = u.id)
    """) == 10, "users owning no workflows"
    assert scalar(settings, """
        SELECT count(*) FROM users u
        WHERE EXISTS (SELECT 1 FROM workflows w WHERE w.owner_user_id = u.id)
          AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.assigned_user_id = u.id)
    """) >= 1, "owner with no assigned tasks"
    assert scalar(settings, """
        SELECT count(*) FROM (
            SELECT owner_user_id FROM workflows
            GROUP BY owner_user_id HAVING count(*) > 1
        ) s
    """) == 2, "owners with multiple workflows"


def test_top_workflow_by_task_count_is_tie_free(settings):
    r = run_readonly(settings, """
        SELECT w.id, count(t.id) AS n
        FROM workflows w JOIN tasks t ON t.workflow_id = w.id
        GROUP BY w.id ORDER BY n DESC LIMIT 2
    """, 10000)
    assert r.error is None
    assert r.rows[0][1] > r.rows[1][1], f"tie at the top: {r.rows}"


def test_top_three_assignees_are_tie_free(settings):
    """"Top 3 users by assigned tasks" must have an unambiguous answer."""
    r = run_readonly(settings, """
        SELECT u.id, count(t.id) AS n
        FROM users u JOIN tasks t ON t.assigned_user_id = u.id
        GROUP BY u.id ORDER BY n DESC LIMIT 4
    """, 10000)
    assert r.error is None
    counts = [row[1] for row in r.rows]
    assert counts[0] > counts[1] > counts[2] > counts[3], f"tie in top 3: {counts}"


def test_seed_is_deterministic(settings):
    a = run_readonly(settings, "SELECT id, full_name, email FROM users ORDER BY id", 10000)
    b = run_readonly(settings, "SELECT id, full_name, email FROM users ORDER BY id", 10000)
    assert a.rows == b.rows


def test_readonly_role_cannot_write(settings):
    r = run_readonly(settings, "INSERT INTO users(id, full_name) VALUES (999,'x')", 10000)
    assert r.error is not None, "read-only role accepted a write"


def test_readonly_role_cannot_drop(settings):
    r = run_readonly(settings, "DROP TABLE tasks", 10000)
    assert r.error is not None, "read-only role accepted DDL"
