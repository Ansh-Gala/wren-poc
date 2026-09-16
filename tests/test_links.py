"""Which cell opens an issue, and which opens a file."""

from __future__ import annotations

from pipeline.links import indices, with_links


def test_the_title_is_what_a_person_clicks():
    """The id is what the route needs; the title is what anyone can read."""
    where = indices(["issue_id", "task_id", "issue_title", "issue_status"])
    assert where["issue"] == {"id_at": 0, "at": 2}


def test_the_id_is_clickable_when_there_is_no_title():
    """A result that projects only the id should still open."""
    where = indices(["issue_id", "issue_status"])
    assert where["issue"] == {"id_at": 0, "at": 0}


def test_no_issue_id_means_nothing_to_follow():
    """Before the view carried an id this was every issue result."""
    assert indices(["task_id", "issue_title", "issue_status"])["issue"] is None


def test_the_file_name_opens_the_file():
    where = indices(["file_name", "file_uri", "file_size"])
    assert where["file"] == {"uri_at": 1, "at": 0}


def test_a_file_with_no_name_falls_back_to_its_uri():
    assert indices(["file_uri"])["file"] == {"uri_at": 0, "at": 0}


def test_an_aggregate_carries_no_links_block_at_all():
    """A count has nothing to follow, and should not be handed empty fields."""
    result = {"columns": ["count"], "rows": [[25]]}
    assert with_links(result, ["count"]) == result
    assert "links" not in with_links(result, ["count"])


def test_no_column_name_is_altered_on_the_way_out():
    """Presentation only, exactly as the initiative block is."""
    result = {"columns": ["issue_id", "issue_title"], "rows": [[1, "test isue"]]}
    out = with_links(result, ["issue_id", "issue_title"])
    assert out["columns"] == ["issue_id", "issue_title"]
    assert out["rows"] == [[1, "test isue"]]
    assert out["links"]["issue"] == {"id_at": 0, "at": 1}


def test_both_targets_can_appear_in_one_answer():
    """A join across attachments and issues is a legitimate question."""
    where = indices(["issue_id", "issue_title", "file_name", "file_uri"])
    assert where["issue"] == {"id_at": 0, "at": 1}
    assert where["file"] == {"uri_at": 3, "at": 2}


def test_the_first_occurrence_wins():
    """A result may project one name twice; the frontend keys rows by index."""
    assert indices(["issue_id", "issue_id"])["issue"]["id_at"] == 0
