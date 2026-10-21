"""The asking user, with what the database knows about them.

Ported from Drupal's IdentityProvider. There the id comes from the session;
here it is the request's user_id (pipeline/run_access.py). Everything else --
the name, every department -- is read from the views product.yaml's `users`
names, exactly as Drupal reads it.

Failure is None, never a fallback id: the model then asks who is asking.
"""

from __future__ import annotations

import re
import time

from database.connection import run_readonly
from pipeline.identity import CallerIdentity

# A table or column name from product.yaml is interpolated: run_readonly
# binds nothing, so only a plain identifier is accepted.
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _plain(block: dict, key: str) -> str | None:
    """One name from a product.yaml users block, or None if absent or not plain."""
    name = block.get(key)
    return name if isinstance(name, str) and _PLAIN_NAME.match(name) else None

# Department data changes without anything telling this process, so a
# resolved identity is trusted for this long and then read again. Drupal's
# cache uses the same figure.
CACHE_TTL_SECONDS = 900

_resolved: dict[int, tuple[float, CallerIdentity]] = {}


def resolve_identity(settings, user_id: int | None) -> CallerIdentity | None:
    """The user with this id, or None when there is no telling who they are.

    The id is cast to int before it reaches the SQL: run_readonly binds
    nothing, so the cast is the sanitisation, as it is in Drupal.
    """
    user_id = int(user_id or 0)
    if user_id <= 0:
        return None
    hit = _resolved.get(user_id)
    if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    from pipeline.metadata import profile

    users = profile().users()
    user_table, id_column, name_column = (_plain(users, k) for k in ("table", "id", "name"))
    name = ""
    if user_table and id_column and name_column:
        result = run_readonly(
            settings,
            f"SELECT {name_column} FROM {user_table} WHERE {id_column} = {user_id} LIMIT 1")
        if not result.error and result.rows and result.rows[0][0] is not None:
            name = str(result.rows[0][0])

    block = users.get("departments") or {}
    dept_table, dept_user, dept_name = (_plain(block, k) for k in ("table", "user_id", "name"))
    departments: list[str] = []
    if dept_table and dept_user and dept_name:
        result = run_readonly(
            settings,
            f"SELECT DISTINCT {dept_name} FROM {dept_table} "
            f"WHERE {dept_user} = {user_id} AND {dept_name} IS NOT NULL ORDER BY {dept_name}")
        if not result.error:
            departments = [str(row[0]).strip() for row in result.rows if str(row[0]).strip()]

    # No product row: a bare id would make the model filter on a missing user.
    if not name and not departments:
        return None
    identity = CallerIdentity(user_id, name, tuple(departments))
    _resolved[user_id] = (time.monotonic(), identity)
    return identity
