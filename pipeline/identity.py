"""Who is asking, and how the model is told.

"My tasks" cannot be answered from the question alone. Until now the answer
was written into the business rules -- "the signed-in user is user id 1
('Admin'); use that literal id" -- which is correct for a benchmark run by one
person and wrong for a website, where it hands every caller the same person's
work.

The fix is to move the value out of the rules and into the request, leaving
the rules to say only which column it compares to. Two properties matter:

The value never comes from the browser. A caller who can supply their own user
id can supply somebody else's, which turns "my tasks" into an impersonation
endpoint. Drupal resolves it from the session; the Python side resolves it
from settings, because a benchmark has no session.

The value never defaults. A missing identity renders nothing, and the business
rule says to ask rather than guess -- falling back to a default id is exactly
the bug being removed, and it fails silently because the answer looks right.

The block is rendered here rather than in prompts.py so that the PHP port has
one function to mirror, and so the wording lives beside the reasoning for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CallerIdentity:
    """The person asking, as much of them as the question could need."""

    user_id: int
    display_name: str = ""
    departments: tuple[str, ...] = field(default_factory=tuple)

    def is_known(self) -> bool:
        return bool(self.user_id)


def render_identity(identity: CallerIdentity | None) -> str:
    """The signed-in user, as a block for the top of the user prompt.

    The user prompt rather than the system prompt, for two reasons. The system
    prompt is byte-compared against a fixture by the parity harness, so a
    per-caller value in it could never be checked. And it is the cached
    prefix: giving every person their own copy of it would give every person
    their own cache entry, which is the opposite of what the 82% cache-read
    rate depends on.

    Nothing here is snake_case, so a sentence the model builds out of it
    cannot trip the identifier guard in redact.safe_clarification.
    """
    if identity is None or not identity.is_known():
        return ""

    lines = [
        "SIGNED-IN USER (resolved by the server from the session, never from "
        "the question)",
        f"  id: {identity.user_id}",
    ]
    if identity.display_name:
        lines.append(f"  name: {identity.display_name}")
    if identity.departments:
        lines.append("  departments: " + ", ".join(identity.departments))
    lines.append("")
    lines.append('"my", "me", "mine", "I" and "our" in the question mean this '
                 "person.")
    # Two, not one: the conversation block is concatenated straight onto this,
    # and a single newline ran the two headings together.
    lines.append("")
    lines.append("")
    return "\n".join(lines)
