"""Guard the prompt against silent growth.

The system prompt once carried metadata/schema_description.yaml and
business_rules.yaml in full: 4769 tokens, paid on every call, growing with
every column added to the database. Wren serves that content on demand now,
so the prompt is constant and small.

These tests fail the moment that regresses -- which is the point. A schema
doubling should cost nothing here; if it does, someone has inlined it again.
"""

from __future__ import annotations

import pytest

from claude.prompts import build_system_prompt, build_user_prompt
from wren_setup.mcp_config import allowed_tools, all_disallowed_tools

tiktoken = pytest.importorskip("tiktoken")

# Generous headroom over the measured 422 tokens: enough to reword the
# procedure, nowhere near enough to inline a schema.
SYSTEM_PROMPT_TOKEN_BUDGET = 900
USER_PROMPT_TOKEN_BUDGET = 200


def _tokens(text: str) -> int:
    return len(tiktoken.get_encoding("o200k_base").encode(text))


def test_system_prompt_is_within_budget():
    actual = _tokens(build_system_prompt())
    assert actual < SYSTEM_PROMPT_TOKEN_BUDGET, (
        f"system prompt is {actual} tokens, over the {SYSTEM_PROMPT_TOKEN_BUDGET} "
        "budget. Has schema or business-rule content been inlined again? "
        "It belongs behind describe_model / get_context."
    )


def test_user_prompt_is_within_budget():
    actual = _tokens(build_user_prompt("How many tasks are overdue?"))
    assert actual < USER_PROMPT_TOKEN_BUDGET


def test_system_prompt_does_not_embed_the_schema():
    """Cost must not scale with the database."""
    prompt = build_system_prompt()
    for leaked in ("owner_user_id", "assigned_user_id", "data_source: postgres"):
        assert leaked not in prompt, (
            f"{leaked!r} appears in the system prompt -- the schema is being "
            "inlined again, so prompt cost now grows with the database."
        )


def test_system_prompt_is_constant():
    """A stable prefix is what makes prompt caching pay off."""
    assert build_system_prompt() == build_system_prompt()


def test_oversized_tools_stay_denied():
    """list_functions alone returns ~19638 tokens -- 46x the whole prompt."""
    denied = set(all_disallowed_tools())
    for tool in ("mcp__wren__list_functions", "mcp__wren__get_mdl",
                 "mcp__wren__describe_schema"):
        assert tool in denied


def test_allowed_and_denied_never_overlap():
    for mode in ("strict", "validated"):
        assert not set(allowed_tools(mode)) & set(all_disallowed_tools())


def test_row_returning_tools_are_denied_in_every_mode():
    denied = set(all_disallowed_tools())
    assert "mcp__wren__run_sql" in denied
    assert "mcp__wren__query_cube" in denied
