"""The prompt must name the values a question can be about.

A column the model cannot enumerate is a column it has to guess at, and the
guess is invisible: asked for AR_NPD_YD_SHIRTING -- the largest business
object type in the database, 59 rows -- the model inferred the valid set from
workflow_code, which genuinely omits it, and correctly concluded from wrong
information that the type does not exist. Two benchmark turns were scored as
failures for a prompt gap.
"""

from __future__ import annotations

import pytest

from claude.prompts import build_lean_system_prompt

pytestmark = pytest.mark.integration


def test_lean_prompt_names_every_business_object_type_in_the_database(settings):
    """The subject column is the one place a wrong guess is unrecoverable.

    Getting a dimension wrong narrows an answer incorrectly; getting the
    subject wrong means there is no answer at all, and the model cannot tell
    the difference between "this type does not exist" and "I was not told
    about it".
    """
    from database.connection import run_readonly

    result = run_readonly(
        settings,
        "SELECT DISTINCT business_object_type FROM tms_business_object_flat "
        "WHERE business_object_type IS NOT NULL",
        15000,
    )
    assert result.error is None, result.error
    live = {str(row[0]) for row in result.rows}
    assert len(live) > 12, "cap is only interesting above MAX_ENUM_VALUES"

    prompt = build_lean_system_prompt()
    missing = sorted(value for value in live if value not in prompt)
    assert not missing, (
        f"{len(missing)} business object type(s) the prompt never names: {missing}"
    )


def test_lean_prompt_warns_about_every_column_that_holds_nothing(settings):
    """A column with no data must not look like a usable one.

    Recovered from a real session: "show average delay in all orders of all
    workflow" produced AVG(current_milestone_delay_days) grouped by workflow,
    which is correct SQL and returned NULL for all twelve rows, because that
    column is NULL in all 307. Valid query, empty column, and nothing in the
    answer distinguishes that from a broken system.

    The schema description warned about exactly one such column by hand and
    said nothing about the other 22. This is the check that keeps the two in
    step, since it reads the answer off the database rather than off a list.
    """
    import yaml
    from pathlib import Path

    from database.connection import run_readonly

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "metadata" / "schema_description.yaml")
        .read_text(encoding="utf-8")
    )
    prompt = build_lean_system_prompt()

    undocumented: list[str] = []
    for table, spec in (doc.get("tables") or {}).items():
        columns = list((spec.get("columns") or {}).keys())
        if not columns:
            continue
        counts = ", ".join(f'count("{c}")' for c in columns)
        result = run_readonly(settings, f"SELECT {counts} FROM {table}", 30000)
        assert result.error is None, f"{table}: {result.error}"

        for column, non_null in zip(columns, result.rows[0]):
            if non_null:
                continue
            description = (spec["columns"][column] or {}).get("description", "")
            # Either wording is fine -- one is generated, one predates it --
            # but the model has to be told, and it is told through the prompt,
            # so the assertion is against the prompt and not just the YAML.
            warned = "NULL in every row" in description or "NULL for every row" in description
            if not (warned and description.split(".")[0] in prompt):
                undocumented.append(f"{table}.{column}")

    assert not undocumented, (
        f"{len(undocumented)} always-NULL column(s) the prompt does not warn about, "
        f"so the model may build an answer on them: {undocumented}"
    )
