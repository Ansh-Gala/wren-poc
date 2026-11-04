"""Settings of the HTTP server that are not in .env: paths, limits and
the messages it sends."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


UI_DIR = ROOT / "ui"


# How many turns of debug detail a conversation keeps for later inspection.
DEBUG_LOG_TURNS = 50


# All users together have used this month's budget (MONTHLY_TOKEN_LIMIT).
# The sentence and the code are Drupal's TokenLimitException's; HTTP 429.
TOKEN_LIMIT_MESSAGE = ("You have exceeded your monthly token limit. "
                       "Please try again next month.")


TOKEN_LIMIT_CODE = "monthly_token_limit"


# Drupal's ChatRuntime::LOCK_WAIT: a second question on a busy chat waits
# this long for the first, then fails rather than queueing forever.
LOCK_WAIT_SECONDS = 30


# Drupal's ConversationStore::STATE_EXPIRY: how long an idle chat keeps its
# working state (filters, subject, a pending clarification). The turns are in
# the tables and do not expire; only this does.
STATE_EXPIRY_SECONDS = 3600


# Aliasing is on and this chat's aliases could not be read. Answering anyway
# would number new aliases from 001 again, over ones the chat already uses.
PII_UNAVAILABLE = ("This chat could not be loaded, so the question was not sent. "
                   "Please try again.")


# The parts of a response a reader sees that the model wrote, and so can
# carry aliases. Rows come from the database and need nothing.
DISPLAYED = ("question", "normalized_question", "resumed_from", "resumed_answering",
             "explanation", "clarification", "followup", "context", "state",
             "state_mutations")


# ------------------------------------------------------------------- http --

# The console is a tool for one person on their own machine. /debug and the
# debug flag hand back the SQL and the real column names, so they answer only
# a caller on this machine, even when --host exposes the rest.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
