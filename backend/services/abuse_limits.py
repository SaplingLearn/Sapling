"""The per-subject budgets on routes that cost money or reach other people.

Each is a sliding window in ``services/request_limits.py`` (the same limiter,
and the same ``stateless_rate_limit`` flag, as quiz generation, study guides,
flashcards, OCR, Gradescope and the topic checklist), charged by
``enforce_abuse_limit`` / ``aenforce_abuse_limit`` AFTER the caller is
authenticated and answered past the budget with a 429, ``Retry-After`` and a
plain sentence the frontend shows as is.

The numbers are bursts a real student never reaches; the daily LLM token
budget (``services/llm_budget.py``) still bounds total model spend. Authenticated
routes are keyed by user id; the public routes (careers, newsletter) by
``client_ip`` — see its docstring for what that address is behind the proxy.
``ABUSE_RATE_LIMIT_MULTIPLIER`` scales all of them for the E2E lanes.
"""
from __future__ import annotations

from services.request_limits import abuse_limit

_MINUTE = 60
_HOUR = 60 * 60

# ── AI tutor (routes/learn.py) ──────────────────────────────────────────────

#: Tutor turns — /chat, /chat/stream, /action, /mode-switch share one budget.
#: A fast typist sends a turn every few seconds; 20 a minute is far past that.
TUTOR_TURN = abuse_limit(
    "tutor-turn", limit=20, window_sec=_MINUTE,
    detail="You're sending tutor messages faster than we can answer them.",
)
#: New tutor sessions — /start-session and /start-session/stream.
TUTOR_SESSION_START = abuse_limit(
    "tutor-start", limit=10, window_sec=_MINUTE,
    detail="You've started a lot of tutor sessions in a short time.",
)

# ── Notes agent actions (routes/notes.py) ───────────────────────────────────

#: summarize / extract-concepts / chat / send-to-tutor on a note share one
#: budget: each is a model call behind a button. (generate-quiz runs no model
#: and spends none of it.)
NOTE_AI_ACTION = abuse_limit(
    "note-ai", limit=20, window_sec=_MINUTE,
    detail="You've asked for a lot of note help in a short time.",
)

# ── Document upload (routes/documents.py) ───────────────────────────────────

#: /upload and /upload/sync share one budget. Each upload runs OCR and several
#: model calls; 30 in ten minutes covers a start-of-term bulk upload.
DOCUMENT_UPLOAD = abuse_limit(
    "doc-upload", limit=30, window_sec=10 * _MINUTE,
    detail="You've uploaded a lot of documents in a short time.",
)
#: Syllabus extraction (routes/calendar.py /extract): OCR plus a model call.
SYLLABUS_EXTRACT = abuse_limit(
    "syllabus-extract", limit=10, window_sec=10 * _MINUTE,
    detail="You've uploaded a lot of syllabi in a short time.",
)

# ── Study-room messages (routes/social.py) ──────────────────────────────────

#: Messages posted, per sender: what everyone else in the room must read.
SOCIAL_MESSAGE_SEND = abuse_limit(
    "social-send", limit=30, window_sec=_MINUTE,
    detail="You're sending messages too quickly.",
)
#: Edits of one's own messages.
SOCIAL_MESSAGE_EDIT = abuse_limit(
    "social-edit", limit=30, window_sec=_MINUTE,
    detail="You're editing messages too quickly.",
)
#: Reaction toggles (each is a write and a live update for the room).
SOCIAL_REACTION = abuse_limit(
    "social-react", limit=60, window_sec=_MINUTE,
    detail="You're reacting too quickly.",
)

# ── Feedback and issue reports (routes/feedback.py; session-authenticated) ──

FEEDBACK_SUBMIT = abuse_limit(
    "feedback", limit=20, window_sec=_HOUR,
    detail="Thanks for all the feedback! You've sent a lot this hour.",
)
ISSUE_REPORT_SUBMIT = abuse_limit(
    "issue-report", limit=10, window_sec=_HOUR,
    detail="You've sent a lot of issue reports this hour.",
)
#: Screenshot uploads for issue reports (5 per report in the UI).
ISSUE_SCREENSHOT_UPLOAD = abuse_limit(
    "issue-screenshot", limit=30, window_sec=_HOUR,
    detail="You've uploaded a lot of screenshots this hour.",
)

# ── Public, unauthenticated routes: keyed by client address ─────────────────

CAREERS_APPLY = abuse_limit(
    "careers-apply", limit=20, window_sec=_HOUR,
    detail="We've received a lot of applications from this connection.",
)
NEWSLETTER_SUBSCRIBE = abuse_limit(
    "newsletter", limit=30, window_sec=_HOUR,
    detail="We've received a lot of sign-ups from this connection.",
)

# The same routes when the caller's address is not a public one: behind a
# proxy that uvicorn has not been told to trust, every caller arrives from the
# proxy's private address, so a per-address budget would be one budget for
# everyone. These ceilings still stop a flood without locking real applicants
# out (request_limits.public_route_limit picks which applies).
CAREERS_APPLY_SHARED = abuse_limit(
    "careers-apply-shared", limit=300, window_sec=_HOUR,
    detail="We're receiving a lot of applications right now.",
)
NEWSLETTER_SUBSCRIBE_SHARED = abuse_limit(
    "newsletter-shared", limit=600, window_sec=_HOUR,
    detail="We're receiving a lot of sign-ups right now.",
)
