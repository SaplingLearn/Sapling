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
/** A profile bio (`BIO_MAX`). */
export const BIO_MAX = 500;
/** Feedback comments and issue-report descriptions (`LONG_TEXT_MAX`). */
export const LONG_TEXT_MAX = 10_000;
