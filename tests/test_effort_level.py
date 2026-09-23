"""CLAUDE_EFFORT_LEVEL=low must reach the CLI.

Two call sites clamped the level to ("medium", "high") independently, so `low`
could be written in .env, loaded into Settings, printed back by any diagnostic
-- and then quietly turned into `medium` on the way to the command line. The
setting appeared to work and did nothing.

That matters now because effort is the latency lever. Measured on gpt-5.6-luna
under the same idea's API name, `reasoning_effort`: medium spends 3.44s before
the first token, low spends 0.99s. A clamp that eats the setting eats the
saving with it.
"""

import json

import pytest

from config.settings import EFFORT_LEVELS, Settings, effort_level
from llm_api.cli_provider import build_command


def _settings(level):
    return Settings(
        pg_host="localhost", pg_port=5432, pg_database="wren_demo",
        pg_user="postgres", cli_lean=True, claude_effort_level=level,
    )


def _effort_in(cmd):
    """The effortLevel the CLI is actually told to use."""
    return json.loads(cmd[cmd.index("--settings") + 1])["effortLevel"]


@pytest.mark.parametrize("level", EFFORT_LEVELS)
def test_every_level_the_cli_accepts_survives_the_journey(level):
    # The list is not invented here. `claude --effort bogus` prints it:
    # "Valid values: low, medium, high, xhigh, max."
    assert _effort_in(build_command("q", None, "strict", _settings(level))) == level


def test_low_specifically_is_not_rewritten_to_medium():
    # The regression this file exists for.
    cmd = build_command("q", None, "strict", _settings("low"))
    assert _effort_in(cmd) == "low"


def test_an_unknown_level_falls_back_to_this_projects_default():
    # Not to Claude Code's default: the CLI ignores a value it does not know
    # and only warns on stderr, which nothing here reads. A run would then be
    # neither what was asked for nor what the settings say.
    assert effort_level("bogus") == "medium"
    assert effort_level("") == "medium"
    assert effort_level(None) == "medium"


def test_the_level_is_normalised_rather_than_rejected():
    assert effort_level("  LOW  ") == "low"
    assert effort_level("High") == "high"


def test_the_pool_honours_the_same_levels_as_the_one_shot_path():
    # The pool serves the questions; the one-shot path is the fallback. They
    # clamped separately, so they could disagree about what a level means.
    from llm_api.cli_pool import ClaudePool

    pool = ClaudePool.__new__(ClaudePool)
    for level in EFFORT_LEVELS:
        pool._effort_level = effort_level(level)
        assert pool._effort_level == level
