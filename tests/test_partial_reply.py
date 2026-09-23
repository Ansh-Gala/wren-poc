"""The one piece of the streaming path that can be wrong silently.

`sql_done_ms` is the whole point of the probe -- it says how much of the wait
is the SQL and how much is the trimmings after it. A scanner that fires one
character early, or misses the close because the SQL contained a quote, would
report a plausible number that is simply untrue. Everything else in the script
is timing arithmetic over bytes that either arrived or did not.
"""

import json

from claude.parser import sql_value_end as find_sql_end


def _mark(text):
    """Where the scanner says the sql value ends."""
    return find_sql_end(text)


def test_marks_the_close_of_a_plain_sql_value():
    text = '{"sql": "SELECT 1", "explanation": "one row"}'
    assert text[:_mark(text)] == '{"sql": "SELECT 1"'


def test_survives_the_escaping_a_provider_actually_streams():
    # Newlines and embedded quotes are the common case, not the edge one: the
    # contract requires \n escapes so the JSON stays valid on one line.
    sql = 'SELECT a\nFROM t WHERE label = "y" AND p = \'z\''
    text = json.dumps({"sql": sql, "explanation": "the open tasks"})
    end = _mark(text)
    # The slice, reparsed, is the SQL that went in -- which is the only
    # definition of "the value ended here" that cannot be fooled.
    assert json.loads(text[len('{"sql": '):end]) == sql


def test_does_not_fire_before_the_closing_quote():
    text = json.dumps({"sql": "SELECT 1", "explanation": "x"})
    end = _mark(text)
    assert _mark(text[:end - 1]) is None


def test_none_while_the_value_is_still_arriving():
    assert _mark('{"sql": "SELECT count(*) FROM ta') is None
    assert _mark('{"s') is None
    assert _mark("") is None


def test_none_for_a_clarification_which_carries_no_sql():
    assert _mark('{"clarify": "which department did you mean?"}') is None


def test_ignores_a_trailing_backslash_rather_than_reading_past_the_end():
    # A chunk can split an escape pair. The scanner steps over both bytes, so
    # the second may not exist yet; it must not report a close for the quote
    # that the escape was hiding.
    assert _mark('{"sql": "SELECT \'a\\') is None
