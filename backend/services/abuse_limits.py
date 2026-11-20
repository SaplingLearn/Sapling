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

# ── Learning-loop tutor (routes/learn_loop.py, audit Z02) ───────────────────
# The loop's own routes charge TUTOR_SESSION_START (its starts) and TUTOR_TURN
# (every turn a student writes: chat, action, a check, probe, post-test or
# prequestion answer, a step attempt, a self-explanation) exactly as the
# legacy routes that delegate to them do. Its no-model writers share this one:
# a hint, the next check, a rating, a report, a review card, the plan approval.

#: The loop's no-model writes. A fast flashcard review is a card a second;
#: 120 a minute is past that.
LOOP_ACTION = abuse_limit(
    "loop-action", limit=120, window_sec=_MINUTE,
    detail="You're moving through the tutor faster than we can keep up.",
)

# ── Notes agent actions (routes/notes.py) ───────────────────────────────────

#: summarize / extract-concepts / chat on a note share one budget: each is a
#: model call behind a button.
NOTE_AI_ACTION = abuse_limit(
    "note-ai", limit=20, window_sec=_MINUTE,
    detail="You've asked for a lot of note help in a short time.",
)
#: send-to-tutor / generate-quiz on a note: no model runs (they hand the note
#: to a tutor session or a quiz, each limited where it runs), so they spend
#: none of the note-AI budget, but a note read still bounds them.
NOTE_LOOKUP = abuse_limit(
    "note-lookup", limit=60, window_sec=_MINUTE,
    detail="You're sending notes to the tutor or a quiz too quickly.",
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

#: /doc/{id}/scan-concepts and /course/{id}/scan-concepts share one budget:
#: each is a concept-scan model call plus a graph write that re-summarises
#: the course. A button a student presses once per document.
CONCEPT_SCAN = abuse_limit(
    "concept-scan", limit=20, window_sec=10 * _MINUTE,
    detail="You've scanned for concepts a lot in a short time.",
)

# ── Flashcards (routes/flashcards.py) ───────────────────────────────────────

#: POST /generate: one model call per concept. The Flashcards page calls it
#: once per missing concept, one after another, so a big set is a steady
#: trickle (each call waits for the last); 30 a minute is past that pace.
FLASHCARD_GENERATE = abuse_limit(
    "flashcard-generate", limit=30, window_sec=_MINUTE,
    detail="You're generating flashcards faster than we can make them.",
)
#: Most cards one /generate (per concept) or /import/generate may ask for.
#: The UI offers 3/5/10 per concept and 10/25/50 per import.
FLASHCARD_GENERATE_MAX_COUNT = 20
FLASHCARD_IMPORT_MAX_COUNT = 50

# ── Knowledge graph (routes/graph.py) ───────────────────────────────────────

#: Concept descriptions (one model call on a cache miss). The quiz home
#: prefetches on hover, so this is a generous per-minute budget.
CONCEPT_DESCRIBE = abuse_limit(
    "concept-describe", limit=60, window_sec=_MINUTE,
    detail="You're asking for concept descriptions too quickly.",
)
#: Add/remove a course or a concept: each can re-summarise the course with a
#: model call inline (course_context_service), so they share one budget.
GRAPH_EDIT = abuse_limit(
    "graph-edit", limit=30, window_sec=_MINUTE,
    detail="You're changing your map too quickly.",
)

# ── Study guides, rooms, settings: model work behind ordinary actions ───────

#: A study-guide check answer (a mastery write; the course re-summary runs
#: after the response).
STUDY_GUIDE_ANSWER = abuse_limit(
    "guide-answer", limit=60, window_sec=_MINUTE,
    detail="You're answering checks too quickly.",
)
#: A study room's overview (its member summary is a model call whenever a
#: member's map changed).
ROOM_OVERVIEW = abuse_limit(
    "room-overview", limit=30, window_sec=_MINUTE,
    detail="You're refreshing the room too quickly.",
)
#: Settings writes (toggling class sharing re-summarises every course after
#: the response).
SETTINGS_WRITE = abuse_limit(
    "settings-write", limit=30, window_sec=_MINUTE,
    detail="You're changing settings too quickly.",
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

# ── Username availability (routes/profile.py; session-authenticated) ────────

#: /api/profile/username/check, per signed-in viewer. The Settings field
#: debounces, so a real student makes a handful; this stops scripted
#: enumeration of the username space.
USERNAME_CHECK = abuse_limit(
    "username-check", limit=30, window_sec=_MINUTE,
    detail="You're checking usernames too quickly.",
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
