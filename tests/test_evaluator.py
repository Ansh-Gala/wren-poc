from datetime import date, datetime
from decimal import Decimal

from benchmark.evaluator import compare_results, normalize_value
from benchmark.models import QueryResult


def R(cols, rows, error=None):
    return QueryResult(columns=cols, rows=rows, duration_ms=1.0, error=error)


def test_row_order_ignored_when_not_ordered():
    assert compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(2,), (1,)]), ordered=False)


def test_row_order_enforced_when_ordered():
    assert not compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(2,), (1,)]), ordered=True)


def test_identical_order_passes_when_ordered():
    assert compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(1,), (2,)]), ordered=True)


def test_column_order_and_alias_ignored():
    assert compare_results(R(["name", "n"], [("a", 1)]), R(["cnt", "who"], [(1, "a")]))


def test_column_permutation_respects_ordering():
    expected = R(["name", "n"], [("a", 1), ("b", 2)])
    actual = R(["n", "name"], [(1, "a"), (2, "b")])
    assert compare_results(expected, actual, ordered=True)


def test_decimal_int_and_float_compare_equal():
    assert compare_results(R(["x"], [(Decimal("2.0"),)]), R(["x"], [(2.0,)]))
    assert compare_results(R(["x"], [(2,)]), R(["x"], [(Decimal("2"),)]))


def test_date_and_iso_string_compare_equal():
    assert compare_results(R(["d"], [(date(2026, 1, 2),)]), R(["d"], [("2026-01-02",)]))


def test_midnight_timestamp_equals_date():
    assert compare_results(
        R(["d"], [(datetime(2026, 1, 2, 0, 0, 0),)]), R(["d"], [(date(2026, 1, 2),)])
    )


def test_null_distinct_from_empty_string_and_zero():
    assert not compare_results(R(["x"], [(None,)]), R(["x"], [("",)]))
    assert not compare_results(R(["x"], [(None,)]), R(["x"], [(0,)]))


def test_null_equals_null():
    assert compare_results(R(["x"], [(None,)]), R(["x"], [(None,)]))


def test_bool_not_conflated_with_integer():
    assert not compare_results(R(["x"], [(True,)]), R(["x"], [(1,)]))


def test_duplicate_rows_are_significant():
    assert not compare_results(R(["a"], [(1,), (1,)]), R(["a"], [(1,)]))


def test_column_count_mismatch_fails():
    assert not compare_results(R(["a"], [(1,)]), R(["a", "b"], [(1, 2)]))


def test_row_count_mismatch_fails():
    assert not compare_results(R(["a"], [(1,), (2,)]), R(["a"], [(1,)]))


def test_empty_results_match():
    assert compare_results(R(["a"], []), R(["b"], []))


def test_error_on_either_side_is_never_a_match():
    assert not compare_results(R(["a"], [(1,)]), R([], [], error="boom"))
    assert not compare_results(R([], [], error="boom"), R(["a"], [(1,)]))


def test_string_whitespace_is_trimmed():
    assert compare_results(R(["s"], [("alice",)]), R(["s"], [(" alice ",)]))


def test_genuinely_different_values_do_not_match():
    assert not compare_results(R(["a"], [(1,)]), R(["a"], [(2,)]))


def test_same_values_wrong_pairing_is_caught():
    """Two columns holding the same value sets but paired wrongly must fail."""
    expected = R(["u", "w"], [("a", "x"), ("b", "y")])
    actual = R(["u", "w"], [("a", "y"), ("b", "x")])
    assert not compare_results(expected, actual)


def test_normalize_value_basics():
    assert normalize_value(None) is not None
    assert normalize_value(Decimal("3.50")) == 3.5
    assert normalize_value(date(2026, 3, 1)) == "2026-03-01"
    assert normalize_value("  hi ") == "hi"
