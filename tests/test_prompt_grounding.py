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
