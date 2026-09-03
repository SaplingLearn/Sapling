"""Showcase overlay for the /gallery product screenshots.

Runs AFTER `seed_local_rich` and rewrites the handful of columns that read as
test data in a screenshot. It is an overlay, not a second dataset, and that is
a deliberate narrowing of the original design.

The rich seed's substance is already photogenic — CS101/MATH210/BIO110 with
real concept names (Recursion, Eigenvalues, DNA Replication), mastery spread
across all four tiers, notes called "Week 1 — Variables", documents called
"cs101-syllabus.pdf". A parallel 875-line seed would have duplicated all of
that to change the few strings that actually give the game away, and then both
copies would have to track every schema change forever.

What does give it away, and what this file fixes:

  - Display names. "Rich Active" and "Sam Second" render in the dashboard
    greeting, every avatar, room member lists and the leaderboard.
  - Room names and the denormalised `room_messages.user_name`, which is a
    plain copy of the sender's name taken at write time.
  - The one message body that greets people by the old room name.

Everything else the screenshots show is left exactly as the rich seed wrote
it. What the *model* would have written is not here at all — that comes from
`agents/function_handlers_showcase.py`, and both are needed: a showcase
overlay with the E2E handlers still photographs "[e2e-function-model]".

LOCAL ONLY. Idempotent: every write is an UPDATE keyed on a rich-* id, so
re-running is a no-op with the same result.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import table                                    # noqa: E402
from db.seed_local_rich import (                                   # noqa: E402
    ROOM_GENERAL,
    USER_ACTIVE,
    USER_ADMIN,
    USER_NEW,
    USER_PENDING,
    USER_SECOND,
)
from services.encryption import encrypt_if_present                 # noqa: E402


def _guard_local() -> None:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    if "127.0.0.1" not in url and "localhost" not in url:
        sys.exit(
            f"REFUSING: SUPABASE_URL {url!r} is not local — "
            "seed_showcase only writes to local."
        )


# (user_id, first, last, email). The signed-in user for the capture is
# USER_ACTIVE, so its first name is what the dashboard greeting renders.
_PEOPLE = [
    (USER_ACTIVE, "Maya", "Ellis", "maya.ellis@bu.edu"),
    (USER_SECOND, "Daniel", "Okafor", "daniel.okafor@bu.edu"),
    (USER_NEW, "Priya", "Raman", "priya.raman@bu.edu"),
    (USER_PENDING, "Tom", "Whitfield", "tom.whitfield@bu.edu"),
    (USER_ADMIN, "Alex", "Chen", "alex.chen@bu.edu"),
]

_NAME_BY_ID = {uid: f"{first} {last}" for uid, first, last, _ in _PEOPLE}

# The study-group room is already called "CS101 Study Group" and stays. Only
# the lounge carries the seed's own branding.
_ROOM_RENAMES = [(ROOM_GENERAL, "Late Night Study Hall")]

# (message_id, replacement text) — only the bodies that name the old room.
_MESSAGE_REWRITES = [
    ("11111111-1111-4111-8111-000000000004", "Welcome to the Late Night Study Hall!"),
]

_counts: dict[str, int] = {}


def _bump(name: str, n: int = 1) -> None:
    _counts[name] = _counts.get(name, 0) + n


def overlay_people() -> None:
    """Rewrite display names on user_profiles, and emails on users.

    `name`, `first_name`, `last_name` and `users.email` are column-encrypted,
    so each value goes through `encrypt_if_present` on the way in — writing
    plaintext here would read back as garbage through the decrypting helpers.
    """
    for uid, first, last, email in _PEOPLE:
        table("user_profiles").update(
            {
                "name": encrypt_if_present(f"{first} {last}"),
                "first_name": encrypt_if_present(first),
                "last_name": encrypt_if_present(last),
            },
            filters={"user_id": f"eq.{uid}"},
        )
        _bump("user_profiles")
        table("users").update(
            {"email": encrypt_if_present(email)},
            filters={"id": f"eq.{uid}"},
        )
        _bump("users")


def overlay_rooms() -> None:
    for room_id, name in _ROOM_RENAMES:
        table("rooms").update({"name": name}, filters={"id": f"eq.{room_id}"})
        _bump("rooms")


def overlay_room_messages() -> None:
    """Fix the denormalised sender name, and the body that names the room.

    `room_messages.user_name` is a plain copy taken at write time, so renaming
    a profile does not reach it — the /social shot would show the new name in
    the member list and the old one on every message.
    """
    for uid, name in _NAME_BY_ID.items():
        table("room_messages").update(
            {"user_name": name},
            filters={"user_id": f"eq.{uid}"},
        )
        _bump("room_messages.user_name")

    for msg_id, text in _MESSAGE_REWRITES:
        # 🔒 text
        table("room_messages").update(
            {"text": encrypt_if_present(text)},
            filters={"id": f"eq.{msg_id}"},
        )
        _bump("room_messages.text")


def main() -> None:
    _guard_local()
    overlay_people()
    overlay_rooms()
    overlay_room_messages()
    print("\nShowcase overlay applied (on top of the rich local seed):")
    for name in sorted(_counts):
        print(f"  {name:26s} updated={_counts[name]}")
    print(f"  {'signed-in user':26s} {_NAME_BY_ID[USER_ACTIVE]} ({USER_ACTIVE})")


if __name__ == "__main__":
    main()
