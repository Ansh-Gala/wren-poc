"""Who is asking, and whether they may run a question.

The caller names itself: user_id in the request. The server binds to this
machine only and trusts the id as sent. There is no default user: a missing
or malformed id is refused, never replaced.

Running a question (POST /ask, /ask/stream, and the full CSV, which runs the
stored SQL again) needs one of the roles in CHATBOT_RUN_ROLES; with none set,
every request may run and no role is read. Roles are
Drupal's, read from vf_user__roles in the business database -- the same
roles the TMS site gives its users -- so this adds no second user list.
A product with its own user list names its role tables in product.yaml's
users block instead (`roles`, `active`).

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
    the user is unknown, blocked, or the roles cannot be read."""
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
    queries = _role_queries(users, table, id_column, int(user_id))
    if queries is None:
        return None
    known = run_readonly(
        settings, f"SELECT 1 FROM {table} WHERE {id_column} = {int(user_id)} LIMIT 1")
    granted = run_readonly(settings, queries[0])
    active = run_readonly(settings, queries[1])
    if known.error or granted.error or active.error:
        return None             # not cached: the next request tries again
    roles = None
    if known.rows and active.rows:
        roles = frozenset({AUTHENTICATED} | {str(r[0]) for r in granted.rows if r[0]})
    _roles[user_id] = (time.monotonic(), roles)
    return roles


def _role_queries(users: dict, table: str, id_column: str,
                  user_id: int) -> tuple[str, str] | None:
    """(the user's role names, a row when the user is active), as SQL.

    Drupal's tables unless product.yaml's users block names `roles`, as a
    product with its own user list does. None when a name there is not
    plain or an `active` value is not a whole number or true/false.
    """
    from pipeline.identity_provider import _PLAIN_NAME, _plain

    roles = users.get("roles")
    if roles is None:
        # A blocked Drupal account cannot sign in, so on Drupal it never asks.
        return ("SELECT roles_target_id FROM vf_user__roles"
                f" WHERE entity_id = {user_id} AND bundle = 'user' AND deleted = 0",
                f"SELECT 1 FROM vf_users_field_data WHERE uid = {user_id} AND status = 1 LIMIT 1")

    names = roles.get("names") or {}
    parts = ([_plain(roles, k) for k in ("table", "user_id", "role_id")]
             + [_plain(names, k) for k in ("table", "id", "name")])
    if not all(parts):
        return None
    role_table, role_user, role_id, name_table, name_id, name = parts
    conditions = [f"{id_column} = {user_id}"]
    for column, value in (users.get("active") or {}).items():
        if not _PLAIN_NAME.match(str(column)):
            return None
        if isinstance(value, bool):
            conditions.append(f"{column} = {'TRUE' if value else 'FALSE'}")
        elif isinstance(value, int):
            conditions.append(f"{column} = {value}")
        else:
            return None
    return (f"SELECT n.{name} FROM {role_table} r JOIN {name_table} n"
            f" ON n.{name_id} = r.{role_id} WHERE r.{role_user} = {user_id}",
            f"SELECT 1 FROM {table} WHERE {' AND '.join(conditions)} LIMIT 1")


def check_run(settings, user_id: int) -> None:
    """Raise RunNotAllowed unless the user holds one of the run roles. With
    no CHATBOT_RUN_ROLES, nothing is checked: every request may run."""
    allowed = set(settings.run_roles)
    if not allowed:
        return
    roles = user_roles(settings, user_id)
    if not roles or not (roles & allowed):
        raise RunNotAllowed("You do not have permission to ask the chatbot.")
