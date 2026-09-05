import pytest

from benchmark.safety import UnsafeSQLError, assert_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users VALUES (1)",
        "UPDATE users SET status='X'",
        "DELETE FROM users",
        "DROP TABLE users",
        "ALTER TABLE users ADD c int",
        "TRUNCATE users",
        "CREATE TABLE t(x int)",
        "GRANT ALL ON users TO x",
        "REVOKE ALL ON users FROM x",
        "SELECT 1; DROP TABLE users",
        "COPY users TO '/tmp/x.csv'",
        "SELECT 1; SELECT 2",
        "",
    ],
)
def test_rejects_dangerous_or_ambiguous_sql(sql):
    with pytest.raises(UnsafeSQLError):
        assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "WITH c AS (SELECT 1 AS n) SELECT n FROM c",
        "SELECT u.full_name, count(t.id) FROM users u "
        "LEFT JOIN tasks t ON t.assigned_user_id=u.id GROUP BY u.full_name",
        "SELECT rank() OVER (ORDER BY id) FROM tasks",
        "SELECT * FROM tasks WHERE due_date < CURRENT_DATE",
        "SELECT a FROM t UNION SELECT b FROM s",
        "SELECT CASE WHEN status='BLOCKED' THEN 1 ELSE 0 END FROM tasks",
        "SELECT count(*) FROM tasks WHERE completed_at IS NULL",
    ],
)
def test_allows_read_only_sql(sql):
    assert_read_only(sql)


def test_forbidden_word_inside_a_string_literal_is_allowed():
    """A task genuinely named 'Update browser matrix' must not trip the gate."""
    assert_read_only("SELECT id FROM tasks WHERE name = 'Update browser matrix'")


def test_forbidden_word_inside_a_comment_is_allowed():
    assert_read_only("SELECT 1 -- we do not DELETE anything here")


def test_unparseable_sql_is_rejected():
    with pytest.raises(UnsafeSQLError):
        assert_read_only("SELEKT nonsense FROM")
