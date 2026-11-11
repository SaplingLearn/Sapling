"""Crisis-support copy: EVERY word a student sees on the crisis-support path.

>>> STATUS: PENDING OWNER REVIEW. <<<
Nothing here reaches a student while the `crisis_support` flag is off, and it
ships off (services/feature_flags.py). Review this file top to bottom, then
work through the checklist in docs/safety/crisis-support.md before turning
the flag on. The frontend card (frontend/src/components/safety/
CrisisSupportCard.tsx) renders these strings and carries no copy of its own,
so this file is the one place to read and to edit.

Tone rules the draft follows: warm, plain, non-clinical; never diagnose or
label the student; never promise confidentiality Sapling can't give; say
plainly that Sapling is a study tool, not a crisis service; offer to keep
studying whenever they're ready.

Campus counseling is configured PER SCHOOL in `CAMPUS_COUNSELING` below (the
one config spot), keyed by the `schools.slug` behind the student's enrolled
courses. A student with no configured school sees
`DEFAULT_CAMPUS_COUNSELING`, which names no phone number on purpose: a wrong
number is worse than none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: What the review has reached. The owner flips this to "approved" (with the
#: date) as the last checklist step; tests pin the draft until then, so the
#: approval is a deliberate, reviewed change.
REVIEW_STATUS: Literal["pending_owner_review", "approved"] = "pending_owner_review"
#: Bumped whenever any string below changes; rides on the client payload so a
#: screenshot or bug report can say which wording a student saw.
COPY_VERSION = "draft-2026-11-08"


@dataclass(frozen=True)
class ResourceAction:
    """One tappable way to reach a resource."""

    kind: Literal["call", "text", "link"]
    label: str
    href: str


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    detail: str
    actions: tuple[ResourceAction, ...] = ()


@dataclass(frozen=True)
class CampusCounseling:
    """One school's counseling service. Leave `phone`/`url` None rather than
    guess: every value here should be checked against the school's own site."""

    name: str
    detail: str
    phone: str | None = None  # dialable, e.g. "617-555-0100"
    url: str | None = None  # https only


# ── The card ────────────────────────────────────────────────────────────────

TITLE = "You don't have to go through this alone"

INTRO: tuple[str, ...] = (
    "It sounds like you might be going through something really painful right "
    "now. I'm glad you said something.",
    "Sapling is a study tool, not a crisis service, so I can't give you the "
    "support you deserve here. These people can, for free, any time:",
)

RESOURCES_HEADING = "People you can reach right now"

LIFELINE_988 = Resource(
    id="lifeline_988",
    name="988 Suicide & Crisis Lifeline",
    detail="Call or text 988 (US). Free and confidential, 24/7.",
    actions=(
        ResourceAction("call", "Call 988", "tel:988"),
        ResourceAction("text", "Text 988", "sms:988"),
        ResourceAction("link", "988lifeline.org", "https://988lifeline.org"),
    ),
)

CRISIS_TEXT_LINE = Resource(
    id="crisis_text_line",
    name="Crisis Text Line",
    detail="Text HOME to 741741 (US). Free, 24/7.",
    actions=(ResourceAction("text", "Text HOME to 741741", "sms:741741?body=HOME"),),
)

EMERGENCY = Resource(
    id="emergency",
    name="Emergency services",
    detail="If you're in immediate danger, call 911 (US).",
    actions=(ResourceAction("call", "Call 911", "tel:911"),),
)

INTERNATIONAL = Resource(
    id="international",
    name="Outside the US",
    detail="Find a free helpline in your country at findahelpline.com.",
    actions=(ResourceAction("link", "findahelpline.com", "https://findahelpline.com"),),
)

CLOSING: tuple[str, ...] = (
    "If you can, let someone you trust know how you're feeling too: a friend, "
    "family member, RA, or professor.",
    "Whenever you're ready, we can keep studying, right where you left off.",
)

#: The card's way back: it closes the card where it shows over the page, and
#: starts a fresh session where it stands in for the learning loop's session.
DISMISS_LABEL = "Back to studying"


# ── Campus counseling: the one per-school config spot ──────────────────────

DEFAULT_CAMPUS_COUNSELING = CampusCounseling(
    name="Your campus counseling center",
    detail=(
        "Most colleges offer free, confidential counseling, and many have a "
        "24/7 line. Search your school's website for \"counseling\"."
    ),
)

#: schools.slug -> that school's counseling service. Empty until the owner
#: adds a VERIFIED entry, e.g.
#:
#:     "bu": CampusCounseling(
#:         name="<the service's name, as the school writes it>",
#:         detail="<hours / walk-in note>",
#:         phone="<a number checked on the school's site>",
#:         url="https://<the school's counseling page>",
#:     ),
#:
#: Students are matched through enrollments -> course_offerings -> courses ->
#: schools; while courses.school_id is unpopulated, everyone sees the default.
CAMPUS_COUNSELING: dict[str, CampusCounseling] = {}


def campus_resource(counseling: CampusCounseling) -> Resource:
    actions: list[ResourceAction] = []
    if counseling.phone:
        actions.append(ResourceAction("call", f"Call {counseling.phone}", f"tel:{counseling.phone}"))
    if counseling.url:
        actions.append(ResourceAction("link", "Website", counseling.url))
    return Resource(
        id="campus_counseling", name=counseling.name, detail=counseling.detail, actions=tuple(actions),
    )


def resources(counseling: CampusCounseling) -> tuple[Resource, ...]:
    """The card's resources, in the order they are shown."""
    return (LIFELINE_988, CRISIS_TEXT_LINE, campus_resource(counseling), EMERGENCY, INTERNATIONAL)
