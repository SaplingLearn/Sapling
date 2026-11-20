/**
 * Length caps on free-text inputs. Each mirrors the server's bound on the
 * same field (backend/models/__init__.py and backend/routes/notes.py), which
 * answers a longer value with a 422 — the input stops the student first.
 */

/** A tutor message or a note-chat message (`CHAT_MESSAGE_MAX`). */
export const CHAT_MESSAGE_MAX = 8000;
/** One study-room message (`ROOM_MESSAGE_MAX`). */
export const ROOM_MESSAGE_MAX = 4000;
/** A note's title and body (`NOTE_TITLE_MAX` / `NOTE_BODY_MAX`). */
export const NOTE_TITLE_MAX = 300;
export const NOTE_BODY_MAX = 200_000;
/** One learning-loop answer field — a check, check-in, review, retention or
 *  prequestion answer or reason, a self-explanation (`GRADER_ANSWER_MAX_CHARS`,
 *  backend learning/params.py; #866 K34). */
export const LOOP_ANSWER_MAX = 4000;
/** A learning-loop goal's target concepts (`LoopGoal.target_node_ids`
 *  max_length; a longer list is a 422). */
export const LOOP_GOAL_MAX_TARGETS = 12;
/** A profile bio (`BIO_MAX`). */
export const BIO_MAX = 500;
/** Feedback comments and issue-report descriptions (`LONG_TEXT_MAX`). */
export const LONG_TEXT_MAX = 10_000;
