"""The filter pills: what is in force, and dropping one of them."""

from __future__ import annotations

from pipeline.context import ConversationState
from pipeline.context_pills import context_pills, drop_by_ref, pill_label, pill_ref


def _state() -> ConversationState:
    state = ConversationState()
    state.active_filters = {
        "task_status": "tms_task_flat.task_status = 'open'",
        "initiative_id": "tms_task_flat.initiative_id = 123",
    }
    state.active_subject = {"column": "initiative_id", "value": "123",
                            "label": "initiative 123"}
    return state


def test_the_refs_are_the_ones_drupal_computes():
    """A pill dropped in one implementation must mean the same in the other.
    The values are what PHP's substr(hash('sha256', ...), 0, 10) returns."""
    assert pill_ref("task_status") == "ed87674c6b"
    assert pill_ref("subject") == "44ce01ae6d"


def test_the_subject_and_the_other_filters_are_shown_once():
    pills = context_pills(_state())
    assert [p["kind"] for p in pills] == ["subject", "filter"]
    assert pills[0] == {"ref": pill_ref("subject"), "label": "initiative 123",
                        "kind": "subject"}
    assert pills[1]["ref"] == pill_ref("task_status")


def test_a_label_is_in_the_readers_words():
    assert pill_label("task_status", "tms_task_flat.task_status = 'open'") == "task status = open"


def test_a_label_that_still_names_something_falls_back_to_the_column():
    """A column-to-column compare would leak a second name."""
    label = pill_label("task_status", "task_status = task_display_status")
    assert label == "task status"


def test_dropping_a_filter_takes_it_off_and_names_it_once():
    state = _state()
    assert drop_by_ref(state, pill_ref("task_status")) is True
    assert "task_status" not in state.active_filters
    assert state.dropped_filters == ["tms_task_flat.task_status = 'open'"]


def test_dropping_the_subject_clears_it_and_names_its_filter():
    state = _state()
    assert drop_by_ref(state, pill_ref("subject")) is True
    assert state.active_subject is None
    assert state.dropped_filters == ["tms_task_flat.initiative_id = 123"]


def test_a_stale_ref_changes_nothing():
    state = _state()
    assert drop_by_ref(state, "0000000000") is False
    assert state.active_filters == _state().active_filters
    assert state.dropped_filters == []


def test_no_state_means_no_pills():
    assert context_pills(ConversationState()) == []
