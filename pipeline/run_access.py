"""Who is asking, and whether they may run a question.

The caller names itself: user_id in the request. The server binds to this
machine only and trusts the id as sent. There is no default user: a missing
or malformed id is refused, never replaced.

Running a question (POST /ask, /ask/stream, and the full CSV, which runs the
stored SQL again) needs one of the roles in CHATBOT_RUN_ROLES. Roles are
Drupal's, read from vf_user__roles in the business database -- the same
roles the TMS site gives its users -- so this adds no second user list.

What a run may do is fixed elsewhere and not by role: one read-only SELECT
(pipeline/safety.py), on a view the registry lists (pipeline/sql_semantics.py),
as the read-only login (DATABASE_READONLY_USER).
"""

from __future__ import annotations

import time

from database.connection import run_readonly

# Drupal's implicit role: every user the database knows has it.
AUTHENTICATED = "authenticated"

# A role taken away should stop working soon, so the cache is short.
CACHE_TTL_SECONDS = 60

_roles: dict[int, tuple[float, frozenset[str] | None]] = {}


class UserIdError(ValueError):
    """The request's user_id is missing or is not a positive whole number."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class RunNotAllowed(Exception):
    """The user may not run questions."""

    code = "run_not_allowed"


def user_id_from(value) -> int:
    """The request's user_id as a positive int. Accepts 12 or "12" only."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise UserIdError("user_id is required", "user_id_required")
    if isinstance(value, bool):
        raise UserIdError("user_id must be a positive whole number", "user_id_invalid")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value <= 0:
        raise UserIdError("user_id must be a positive whole number", "user_id_invalid")
    return value


def user_roles(settings, user_id: int) -> frozenset[str] | None:
    """The user's roles, with "authenticated" when the user exists. None when
    the user is unknown or the roles cannot be read."""
    hit = _roles.get(user_id)
    if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    # user_id is an int, so it is safe in the text: run_readonly binds nothing.
    # The user table is product.yaml's, and plain names only.
    from pipeline.identity_provider import _plain
    from pipeline.metadata import profile

    users = profile().users()
    table, id_column = _plain(users, "table"), _plain(users, "id")
    if not table or not id_column:
        return None
    known = run_readonly(
        settings, f"SELECT 1 FROM {table} WHERE {id_column} = {int(user_id)} LIMIT 1")
    granted = run_readonly(
        settings, "SELECT roles_target_id FROM vf_user__roles"
        f" WHERE entity_id = {int(user_id)} AND bundle = 'user' AND deleted = 0")
    if known.error or granted.error:
        return None             # not cached: the next request tries again
    roles = None
    if known.rows:
        roles = frozenset({AUTHENTICATED} | {str(r[0]) for r in granted.rows if r[0]})
    _roles[user_id] = (time.monotonic(), roles)
    return roles


def check_run(settings, user_id: int) -> None:
    """Raise RunNotAllowed unless the user holds one of the run roles."""
    allowed = set(settings.run_roles)
    roles = user_roles(settings, user_id) if allowed else None
    if not roles or not (roles & allowed):
        raise RunNotAllowed("You do not have permission to ask the chatbot.")
