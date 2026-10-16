"""The console's user, with what the database knows about them.

Ported from Drupal's IdentityProvider. There the id comes from the session;
this console is a tool for one person, so it comes from CHATBOT_USER_ID in
.env. Everything else -- the name, every department -- is read from the TMS
views, exactly as Drupal reads it.

Failure is None, never a fallback id: the model then asks who is asking.
"""

from __future__ import annotations

import time

from database.connection import run_readonly
from pipeline.identity import CallerIdentity

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

    name = ""
    result = run_readonly(
        settings, f"SELECT user_name FROM tms_user_flat WHERE user_id = {user_id} LIMIT 1")
    if not result.error and result.rows and result.rows[0][0] is not None:
        name = str(result.rows[0][0])

    departments: list[str] = []
    result = run_readonly(
        settings,
        "SELECT DISTINCT department FROM tms_user_department_flat "
        f"WHERE user_id = {user_id} AND department IS NOT NULL ORDER BY department")
    if not result.error:
        departments = [str(row[0]).strip() for row in result.rows if str(row[0]).strip()]

    # No TMS row: a bare id would make the model filter on a missing user.
    if not name and not departments:
        return None
    identity = CallerIdentity(user_id, name, tuple(departments))
    _resolved[user_id] = (time.monotonic(), identity)
    return identity
