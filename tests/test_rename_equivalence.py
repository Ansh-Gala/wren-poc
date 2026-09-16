from scripts.verify_rename_equivalence import verify_pairs


def test_identical_queries_agree():
    assert verify_pairs([("SELECT 1 AS a", "SELECT 1 AS a")]) == []


def test_differing_queries_are_reported():
    failures = verify_pairs([("SELECT 1 AS a", "SELECT 2 AS a")])
    assert len(failures) == 1
    assert "row 0" in failures[0]


def test_a_column_rename_is_not_a_difference():
    """Values are compared positionally. The heading is meant to change."""
    assert verify_pairs([("SELECT 1 AS initiative_id",
                          "SELECT 1 AS initiative_id")]) == []


def test_a_broken_new_query_is_reported_not_raised():
    failures = verify_pairs([("SELECT 1", "SELECT * FROM tms_nope")])
    assert len(failures) == 1
    assert "new query failed" in failures[0]


def test_null_is_not_confused_with_the_string_none():
    """A NULL and the text 'None' are different data, however they print."""
    failures = verify_pairs([("SELECT NULL AS a", "SELECT 'None' AS a")])
    assert len(failures) == 1


def test_row_order_does_not_matter():
    assert verify_pairs([
        ("SELECT 1 AS a UNION ALL SELECT 2", "SELECT 2 AS a UNION ALL SELECT 1"),
    ]) == []
