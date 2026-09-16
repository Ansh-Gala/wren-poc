from scripts.verify_rename_equivalence import verify_pairs


def test_identical_queries_agree():
    assert verify_pairs([("SELECT 1 AS a", "SELECT 1 AS a")]) == []


def test_differing_queries_are_reported():
    failures = verify_pairs([("SELECT 1 AS a", "SELECT 2 AS a")])
    assert len(failures) == 1
    assert "row 0" in failures[0]


def test_a_column_rename_is_not_a_difference():
    """Values are compared positionally. The heading is meant to change."""
    assert verify_pairs([("SELECT 1 AS business_object_id",
                          "SELECT 1 AS initiative_id")]) == []


def test_a_broken_new_query_is_reported_not_raised():
    failures = verify_pairs([("SELECT 1", "SELECT * FROM tms_nope")])
    assert len(failures) == 1
    assert "new query failed" in failures[0]
