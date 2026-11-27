# W7.8 — Practice vs Exam Twin evidence rules

**Status:** landed (rules + server enforcement + UI labels; timer UX deferred)  
**Plan row:** Alvar trilogy W7.8  
**Branch:** `feat/learning-loop-reland`  
**Code:** `backend/learning/quiz_session_mode.py`

## Rules

| Mode | Wire value | Mastery evidence | Misconceptions (A146) | Tools (Ask / help) | Farm claim (A100) |
|---|---|---|---|---|---|
| **Practice** | `practice` (default) | Yes — lint (A132) + gate (A145) → farm → help floor → `apply_graph_update` | Yes when `quiz_misconceptions` on | Allowed | Claims rolling 24h window |
| **Exam Twin** | `exam_twin` | **No** — score only | No | Refused (409 on quiz-ask) | **Does not claim** |

**Closest existing modes before this slice:** default Quiz home = Practice; client `feedback: at-end` ≈ Exam Twin feedback timing only (never changed evidence). Gate verdict `practice` (A145) is item economy, not a session mode. Learn post-test remains the delayed learning-gain measure — Exam Twin is not a second post-test.

## Why Exam Twin writes no mastery

Plan: Practice = learning evidence path; Exam Twin = timed, post-test-*like*, tool-light — **must not** double-count daily evidence. Skipping the write *and* the farm claim is the strong form: a dress rehearsal neither moves `p_known` nor burns the window a later Practice round needs.

## Wire

- `POST /api/quiz/generate` body: `session_mode` ∈ `{practice, exam_twin}` (default `practice`).
- Stored on `quiz_attempts.session_mode` (migration `20261124005521_quiz_attempts_session_mode.sql`) **only when Exam Twin** — Practice uses the column DEFAULT so flags-off digests stay byte-identical.
- Echoed on generate (Exam Twin only) + get-attempt (parsed; missing → Practice); submit reads the **stored** mode (client cannot flip evidence after generate).
- UI: Mode row on Adjust / Settings (`Practice` / `Exam Twin`); Ask hidden in Exam Twin; results note when mastery unmoved reason is `exam_twin`.

## Non-goals (this slice)

- Full session timer / framed exam sheet (design kit 7.18) — document only; mode is ready for them.
- New feature flag / flag enable.
- Anthropic / new LLM slots.
- Changing A143–A147 flag defaults.

## Tests

- `backend/tests/test_quiz_session_mode.py` — pure rules + submit skips evidence / ask refuses.
- Frontend: mode labels + Ask hidden (`QuizSettings` / `QuizQuestion` / results note).
