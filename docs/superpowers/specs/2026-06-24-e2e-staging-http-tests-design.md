# HTTP End-to-End Tests Against Staging — Design Spec

## 1. Context & goal

The DB modular redesign (migrations 0019–0028, epic `epic/db-modular-redesign`) rewired the
entire backend onto a new schema. It is validated by **790 mocked unit tests** and an **ad-hoc
14-check service-level run** against the seeded staging DB. Mocks cannot catch schema-mismatch
at runtime — exactly the class of bug staging seeding surfaced (`0028` `course_code NOT NULL`,
a *write*-path failure invisible to read-only checks).

**Goal:** a committed, repeatable **HTTP end-to-end test** that drives the real FastAPI routes
(routing + auth guard + request/response serialization + services) against the **real seeded
staging database**, covering **every endpoint the redesign touched** — reads *and* writes —
so a future migration can be validated the same way before any cutover.

**Non-goal (stays a manual gate):** testing the *deployed* staging app over its public URL.
That sits behind Cloudflare Access + real sign-in and remains the human browser smoke-test in
the `epic → main` cutover PR (#279). This spec is the automated layer beneath that.

## 2. Approach

Run the app **in-process** with FastAPI's `TestClient`, **outside pytest** (so `conftest.py`'s
hermetic DB mock and auth bypass do NOT apply), with `.env.staging` loaded so `db.connection`
talks to the seeded staging DB. This gives the full HTTP + auth + service stack against real
data, with no deploy and no Cloudflare Access in the path.

Chosen over (a) read-only validation [misses the write paths where the rewire risk lives] and
(c) deployed-URL testing [needs a deploy + CF Access; that's the manual gate].

## 3. Architecture & components

A single runner: **`backend/db/e2e_staging_http.py`**, invoked as
`dotenv -f .env.staging run -- python -m db.e2e_staging_http`.

- **App + client:** `from main import app`; `client = TestClient(app)`. No pytest, no fixtures.
- **Auth (real):** mint a valid HMAC session for the throwaway user via the app's own
  token-issuance/signing (the same path `services/auth_guard` verifies) using the staging
  `SESSION_SECRET`, and attach it as the `sapling_session` cookie on the client. This exercises
  `get_session_user_id` / `require_self` for real (and lets us assert a 401 with no cookie).
- **Throwaway identity:** the run owns a `e2e-<runid>` user (+ `user_profiles` row, with `name`
  encrypted via `encrypt_if_present`). `runid` is passed in (no `Date.now()`/random at import)
  so the run is deterministic and re-runnable.
- **Isolation + teardown:** every write is namespaced to that user. A `finally` block deletes
  the user row — FK `ON DELETE CASCADE` (0023/0024/0025) sweeps its enrollments, graph nodes/
  edges/events, gradebook rows, study artifacts — and explicitly removes any `course_offering`
  the run materialized via `resolve_offering(create=True)`. The shared `seed-…` demo data is
  never touched.
- **LLM-tolerance:** endpoints that call Gemini (quiz generation, course-context summary, note
  summarize) assert on **structure / status / fallback**, never model text, so the run needs no
  Gemini key.
- **Output:** each check prints `PASS`/`FAIL <endpoint> <assertion>`; a final summary prints
  `N/M passed`; the process exits non-zero on any failure (CI-able later). Teardown always runs.

## 4. Coverage — every endpoint the redesign touched

Read + write journeys. Each asserts HTTP status + the key response fields the rewire changed.

- **Auth/session:** 401 with no cookie; 200 with the minted session (the harness foundation).
- **Academics:** `GET /api/semesters` (new, lists terms) · `GET /api/onboarding/courses`
  (abstract catalog search) · `POST /api/onboarding/profile` (enroll → resolve/create the
  current-term offering) · assert the enrollment landed against an `offering_id`.
- **Graph:** `GET /api/graph/<u>/courses` (each course carries its `term`) · `GET /api/graph/<u>`
  (nodes/edges/stats/subject-roots) · `POST` add-course (abstract id → offering enrollment) ·
  `PATCH` color + nickname · `GET` recommendations · `DELETE` course.
- **Gradebook:** `POST` category (+ `drop_lowest`) · `POST` assignment (🔒 points) ·
  `GET /summary?semester=` · `GET /gpa` (per-term + cumulative) · `PATCH /courses/{id}/curve`
  (new) · `PATCH /courses/{id}/scale` · assert drop-lowest math + `decrypt_numeric` of points.
- **Identity:** `GET /api/profile/<u>` (display name from `user_profiles`) · `PATCH` profile
  (writes `user_profiles`) · settings get/patch · `GET /api/users` (decrypted names via
  `services/profiles`) · `GET /api/auth/me`.
- **Study:** create + read a note and a document on an offering (offering-keyed) · soft-delete a
  note and confirm it drops from reads · study-guide + flashcards read paths.
- **Quiz:** `POST` generate + submit → assert the mastery write routed through
  `apply_graph_update` (a `node_mastery_events` row appears; no `graph_nodes.mastery_events`).
- **Analytics/Social:** `GET /api/social/students` (enrollments→course names; names decrypted).
- **Ops:** `POST /api/feedback` + an issue report (text PK + FK to the throwaway user).

## 5. Error handling

Every journey is wrapped; a failure records `FAIL` and continues (so one broken endpoint doesn't
hide the rest). Teardown runs in `finally` regardless. Network/DB errors surface the HTTP body
(PostgREST messages) like the seed runner does, so a 4xx is diagnosable in one shot.

## 6. How to run / where it lives

`backend/db/e2e_staging_http.py`, committed. Run:
`dotenv -f .env.staging run -- python -m db.e2e_staging_http`. Module docstring marks it
**STAGING-ONLY** (writes a throwaway user) and reads env only via `db/connection.py::table()` —
no hardcoded URLs/keys, no secrets printed.

## 7. Validation criteria

The run prints `N/N passed`, exits 0, and leaves the staging DB exactly as it found it (the
throwaway user + its rows + any materialized offering gone; seed demo data intact). A re-run
produces the same result.

## 8. Out of scope

Deployed-URL/browser testing (the manual cutover gate); load/perf; the unchanged
Social-rooms/gamification/calendar/careers/admin surfaces except where the redesign touched them
(`social/students`, `feedback`).
