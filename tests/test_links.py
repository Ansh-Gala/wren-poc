"""Which cell opens what, and how: product.yaml's entities with `open`."""

from __future__ import annotations

from pipeline.links import indices, with_links


def link(columns, action, **match):
    """The one link of this action (and these fields) the columns carry, or None."""
    found = [item for item in indices(columns)
             if item["action"] == action and all(item.get(k) == v for k, v in match.items())]
    assert len(found) <= 1, found
    return found[0] if found else None


ISSUE = {"url": "/view-issue/{id}?destination=/issues", "encode": "base64"}


def test_the_title_is_what_a_person_clicks():
    """The id is what the route needs; the title is what anyone can read."""
    item = link(["issue_id", "task_id", "issue_title", "issue_status"], "url", **ISSUE)
    assert (item["value_at"], item["at"]) == (0, 2)


def test_the_id_is_clickable_when_there_is_no_title():
    """A result that projects only the id should still open."""
    item = link(["issue_id", "issue_status"], "url", **ISSUE)
    assert (item["value_at"], item["at"]) == (0, 0)


def test_no_issue_id_means_nothing_to_follow():
    """Before the view carried an id this was every issue result."""
    assert link(["task_id", "issue_title", "issue_status"], "url", **ISSUE) is None


def test_the_file_name_opens_the_file():
    item = link(["file_name", "file_uri", "file_size"], "download")
    assert (item["value_at"], item["at"]) == (1, 0)


def test_a_file_with_no_name_falls_back_to_its_uri():
    item = link(["file_uri"], "download")
    assert (item["value_at"], item["at"]) == (0, 0)


def test_an_aggregate_carries_no_links_block_at_all():
    """A count has nothing to follow, and should not be handed empty fields."""
    result = {"columns": ["count"], "rows": [[25]]}
    assert with_links(result, ["count"]) == result
    assert "links" not in with_links(result, ["count"])


def test_no_column_name_is_altered_on_the_way_out():
    """Presentation only, exactly as the row colour is."""
    result = {"columns": ["issue_id", "issue_title"], "rows": [[1, "test isue"]]}
    out = with_links(result, ["issue_id", "issue_title"])
    assert out["columns"] == ["issue_id", "issue_title"]
    assert out["rows"] == [[1, "test isue"]]
    assert out["links"] == [{"value_at": 0, "action": "url", **ISSUE, "at": 1}]


def test_both_targets_can_appear_in_one_answer():
    """A join across attachments and issues is a legitimate question."""
    columns = ["issue_id", "issue_title", "file_name", "file_uri"]
    assert link(columns, "url", **ISSUE)["at"] == 1
    assert link(columns, "download")["at"] == 2


def test_the_first_occurrence_wins():
    """A result may project one name twice; the frontend keys rows by index."""
    assert link(["issue_id", "issue_id"], "url", **ISSUE)["value_at"] == 0


def test_a_task_is_a_button_on_its_own_id():
    """A task opens through its own button: no readable cell to point at."""
    item = link(["task_display_name", "task_id"], "url", button="View Task")
    assert item == {"value_at": 1, "action": "url", "url": "/ticket-details/{id}?destination=/tickets",
                    "encode": "plain", "button": "View Task"}
    assert "at" not in item


def test_a_task_alone_is_enough_for_a_links_block():
    result = {"columns": ["task_id"], "rows": [[7]]}
    assert with_links(result, ["task_id"])["links"][0]["button"] == "View Task"


def test_no_task_id_means_no_task_button():
    assert link(["task_display_name"], "url", button="View Task") is None


def test_the_initiative_opens_its_popup_from_either_id_name():
    """bo_id is the old name of initiative_id; both open the same popup."""
    for columns in (["initiative_id"], ["task_id", "bo_id"]):
        item = link(columns, "popup")
        assert item["popup"] == "BODetails" and item["param"] == "bo_id"
        assert item["at"] == item["value_at"] == columns.index(columns[-1])


def test_a_cell_takes_the_first_link_that_claims_it():
    """No cell opens two things."""
    ats = [item["at"] for item in indices(["initiative_id", "issue_id", "file_uri"]) if "at" in item]
    assert len(ats) == len(set(ats))
