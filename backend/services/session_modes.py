"""`sessions.mode` values shared by the tutor and the learning loop's review queue.

A `sessions` row with mode 'review' is a learning-loop daily review session
(learning/review.py, PKG-12; spec §13 A9): one per user, course and UTC day, whose
`loop_state` holds the successive-relearning counters. It is NOT a tutor session:
every reader that lists, counts, resumes or personalises from tutor sessions adds
`NOT_REVIEW` to its filters (sessions.mode is NOT NULL, 0025, so `neq` never drops a
row with a NULL mode). A review session announces itself with the
`review.session_started` event, never `session.started`.

Plain constants, no imports: the legacy readers import this module, so it must not
pull in the (gated) learning layer.
"""

REVIEW_MODE = "review"

#: PostgREST filter fragment: every session except the review queue's.
NOT_REVIEW: dict[str, str] = {"mode": f"neq.{REVIEW_MODE}"}
