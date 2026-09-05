from claude.parser import parse_sql


def test_strategy_json_object():
    p = parse_sql('{"sql": "SELECT 1"}')
    assert p.sql == "SELECT 1"
    assert p.strategy == "json"


def test_strategy_sql_fence():
    p = parse_sql("Here you go:\n```sql\nSELECT * FROM users\n```\nHope that helps.")
    assert p.sql == "SELECT * FROM users"
    assert p.strategy == "sql_fence"


def test_strategy_generic_fence():
    p = parse_sql("```\nSELECT 1\n```")
    assert p.sql == "SELECT 1"
    assert p.strategy == "generic_fence"


def test_strategy_embedded_json():
    p = parse_sql('Result below.\n{"sql": "SELECT 2"}\nDone.')
    assert p.sql == "SELECT 2"
    assert p.strategy == "embedded_json"


def test_strategy_bare_statement():
    p = parse_sql("SELECT id FROM tasks WHERE status = 'TODO'")
    assert p.sql.startswith("SELECT id")
    assert p.strategy == "bare"


def test_prefers_last_sql_fence_over_earlier_draft():
    p = parse_sql("```sql\nSELECT 1\n```\nActually:\n```sql\nSELECT 2\n```")
    assert p.sql == "SELECT 2"


def test_cte_is_recognised():
    p = parse_sql("WITH c AS (SELECT 1 AS n) SELECT n FROM c")
    assert p.sql.startswith("WITH c AS")
    assert p.strategy == "bare"


def test_returns_none_when_no_sql():
    p = parse_sql("I could not answer that.")
    assert p.sql is None
    assert p.strategy == "none"


def test_empty_input_returns_none():
    assert parse_sql("").sql is None
    assert parse_sql("   ").strategy == "none"


def test_strips_comments_and_trailing_semicolon():
    p = parse_sql("```sql\n-- find users\nSELECT 1;\n```")
    assert p.sql == "SELECT 1"


def test_strips_block_comments():
    p = parse_sql("```sql\n/* preamble */ SELECT 1\n```")
    assert p.sql == "SELECT 1"


def test_json_with_query_key_is_accepted():
    assert parse_sql('{"query": "SELECT 3"}').sql == "SELECT 3"


def test_multiline_sql_fence_is_preserved():
    p = parse_sql("```sql\nSELECT a,\n       b\nFROM t\n```")
    assert "SELECT a," in p.sql and "FROM t" in p.sql


def test_prose_before_bare_statement_is_dropped():
    p = parse_sql("The answer is:\nSELECT count(*) FROM tasks")
    assert p.sql == "SELECT count(*) FROM tasks"


def test_generic_fence_ignored_when_not_sql():
    p = parse_sql("```python\nprint('hi')\n```")
    assert p.sql is None


def test_json_fence_containing_sql_object():
    p = parse_sql('```json\n{"sql": "SELECT 4"}\n```')
    assert p.sql == "SELECT 4"
    assert p.strategy == "embedded_json"
