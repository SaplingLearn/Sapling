# Cleanup & Hardening Program

State of the multi-wave cleanup-and-hardening program. Read this at session start
instead of being re-briefed. **Update this file as waves land — don't duplicate it.**

## Done (all merged, CI-green)

- **Wave 1** — 8 scoped PRs. Security: #206 auth-gated the unauthenticated
  `/api/users` decrypted-name dump (now 401); #204 closed a cross-user quiz IDOR
  (now 404) — each with a negative test that fails on pre-fix code.
  Cleanups: #200, #201, #202, #203, #205, #207.
- **Infra** — #162 CI pipeline (GitHub Actions: backend pytest + frontend
  eslint/tsc/vitest on every PR and push). #208 time-bomb test fixed.
  #210 test_documents_routes hermetic and un-quarantined (gated suite ~614, all
  genuinely passing). #212 ESLint bulk-suppressions ratchet (every rule at error,
  164 existing violations baselined, new ones fail CI).
- **Wave 2 Phase 1** (PR #213) — design-system consolidation: #104 token
  consolidation (pixel-identical), #102 glassmorphism removed, #103 gradient-text
  headings → solid, #106 fabricated hero stat cards removed, #112 polish (warm
  off-white panels, state cues by shape/label not color-only, DM Sans).
- **Wave 2 Phase 2** (PR #214) — a11y: #107 contrast fixes (five token/control AA
  fixes; primary button moved to `--brand-forest` — keep it there), #108 focus
  rings on 13 inputs, accessible names, SignInModal focus trap, graph/plot a11y.
  Final commit: rarity toast label set to neutral `var(--text)` (last #107 cue
  finding; verified 17.28:1 on all five tiers — rarity stays signaled by the
  colored dot plus the tier name as text).
- **Rarity token cleanup** (PR #217, merged and live) — single-sourced the
  `--rarity-*` tokens: deleted the dead earlier `:root` block in `globals.css`
  (the ~line-107 one; the later block is what renders) and fixed legendary in
  the surviving block from `var(--brand-progress)` (#e8a33a, 2.10:1) to
  `#b4862c` — re-measured 3.20:1 / 3.15:1 against the two `--bg-panel` values,
  over the 3:1 non-text bar. Hardcoded per-component rarity color maps in
  ProfileView and Achievements replaced with the canonical tokens; TitleFlair
  rarity text moved to neutral `var(--text)` with the literal tier name
  appended. Post-merge main checks all green (pytest, lint+tsc+vitest, CodeQL,
  Workers build), and production verified serving the new CSS (live bundle has
  exactly one `--rarity-legendary`, value `#b4862c`).

Wave 2 is closed.

## Wave 3 — security hardening

Backend/data security, driven by the contract/security audit
(`docs/backend-contract-bug-audit.md`). Eleven scoped PRs (each with a negative
test that fails on pre-fix code) plus a production database lockdown that was
applied out of band and lives in no merged PR — recorded below because it's the
most important part.

- **Merged security PRs** (all CI-green; one line each):
  - **#219** — gate `/api/gemini-test` behind `require_admin` (was an
    unauthenticated live-LLM cost/key oracle).
  - **#220** — newsletter stops leaking raw exception text; careers upload
    bounded (5 MB bounded-read 413, PDF/DOC/DOCX allowlist 415, input
    validation 422).
  - **#221** — validate `COOKIE_DOMAIN` + same-origin CSRF check on the session
    route.
  - **#222** — gate `/profile/[userId]` in the middleware (PROTECTED + matcher);
    it was enumerable unauthenticated.
  - **#223** — ruff lint ratchet (E4/E7/E9/F, 94 existing violations baselined in
    `backend/ruff.toml`, new ones fail CI) wired into CI; deduped
    `email-validator` (#194).
  - **#224** — scope calendar `export_to_google` (read + write-back) by
    `user_id`; closed a P0 cross-user IDOR leaking decrypted assignment notes.
  - **#225** — scope `search_course_materials` by `user_id`; stopped another
    student's documents leaking into the tutor/note-chat LLM context.
  - **#226** — encrypt syllabus-extracted assignment notes at the write boundary
    (merged earlier; live backfill was 0 rows, so no migration was needed).
  - **#227** — decrypt gradebook-create and profile-settings responses (were
    returning ciphertext to the owning user).
  - **#228** — `validate_config()` at startup + `SESSION_SECRET` ≥32-byte check;
    unsigned-session OAuth fallback fail-closed outside local
    (`APP_ENV`/`IS_LOCAL`).
  - **#229** — OCR extract endpoints require auth (401), a 20 MB bounded read
    (413), and a per-user rate limit (429); shared `services/request_limits.py`.
  - **#230** — realtime room chat re-fetches via the decrypting REST endpoint
    instead of rendering ciphertext; removed the dead `room_reactions`
    subscription (that table isn't in the realtime publication, so it never
    fired).
- **#234** — hotfix: the new ruff gate (#223) flagged an unused import in
  already-merged #226 test code, turning `main` red until it was removed.
  **Lesson: when landing a new lint gate, confirm `main` is clean under it
  at merge — pre-existing merged code isn't in the gate's baseline.**

### Production RLS lockdown (applied out of band — recorded here, no merged PR)

- **Exposure:** the Supabase `anon` role had full read AND write
  (SELECT/INSERT/UPDATE/DELETE) on 38 of 40 public tables via PostgREST, and the
  anon key ships in the frontend bundle. So anyone with that key could read and
  write the entire database — including self-assigning admin via `user_roles` —
  bypassing the FastAPI backend and every `require_self` check. Confirmed live:
  an anon `curl` returned a real `users` row before the lockdown, `permission
  denied` (SQLSTATE 42501) after. Live since the project launched (~Feb 2026).
- **Remediation:** `ENABLE ROW LEVEL SECURITY` + `REVOKE` anon DML on the 38
  tables, applied directly to prod via the Supabase SQL Editor on 2026-06-13.
  `service_role` is `rolbypassrls`, so the backend (service key) is unaffected
  and keeps functioning. SQL is recorded in **#232**, kept open as the applied
  record (do not merge); plan + verification in
  `docs/security/rls-lockdown-plan.md`.
- **Blast-radius audit (came back clean):**
  - `oauth_tokens` access/refresh tokens were AES-GCM **encrypted** — verified in
    both the stored data and the encrypt/decrypt code paths — so **no Google
    token rotation was required**.
  - `sessions` holds no replayable credential (auth is a stateless HMAC cookie;
    there is no server-side session-token store).
  - Admin audit clean: 4 admins + 1 vip, all real recognized accounts, all
    granted in a single 2026-05-04/05 window; nothing granted during the
    exposure window after.
- **Caveat (follow-up):** `sessions.summary_json` (and likely `messages.content`)
  are stored **plaintext**, contradicting the CLAUDE.md encrypted-columns list,
  so they were anon-readable during the window. Not credentials, but a real
  data-exposure gap — encrypt them and correct the docs (tracked below).

Wave 3 merges are closed; the open security tracks are in the backlog below.

## Backlog / known items

- **Deploy the Wave-3 route-leak fixes to prod.** #224/#225/#227 (and
  #220/#226/#228/#229) are backend changes on `main` but "not closed until on
  prod" — the backend deploy is external (not in-repo); confirm it landed.
- **#231 storage hardening (the last live exposure):** the `application_resumes`
  bucket is still public-read (résumé PII), and `issues-media-files` is public +
  anon-writable. Plan in `docs/security/storage-hardening-plan.md`.
- **#231 realtime JWT bridge (option a):** restores room-chat realtime under RLS
  (mint a Supabase JWT at login + a membership-scoped RLS policy). Design in
  `docs/security/realtime-jwt-bridge-design.md`; flagged complexity is JWT
  refresh (30-day session vs ~1h JWT).
- **Encrypt `sessions.summary_json` + `messages.content`** and fix the CLAUDE.md
  gotchas list (both are listed as encrypted but stored plaintext — see the
  Wave 3 caveat).
- **Queued security follow-ups, awaiting review/merge:** **#235** (scope
  assignment update/delete/sync write filters by `user_id` — defense-in-depth)
  and **#236** (`.toLowerCase()` `COOKIE_DOMAIN` before validation).
- **3 moderate Dependabot vulnerabilities** on the default branch (as of
  2026-06-12) — https://github.com/SaplingLearn/Sapling/security/dependabot
- **PR #96** (feat/knowledge-graph-3d): pre-existing feature branch, outside this
  program — leave it alone.
- **GTM-Builds #173**: workers.dev → custom-domain hardening, deferred until a
  domain exists. Don't re-raise.

## Conventions (keep all of these)

- One scoped commit per issue; tight diffs.
- No parallel implementation subagents on shared files (globals.css, design
  tokens) — that caused worktree contamination in Wave 1. Use worktree-relative
  paths. A fresh-context verifier subagent per commit (re-check diff scope;
  re-measure ratios for contrast work) is the right use of delegation.
- Audit every "done" against an actual tool result before reporting it — no
  fabricated status.
- Merges are CI-gated on the Actions pipeline. "Workers Builds: frontend"
  (Cloudflare) is a non-required deploy mirror; if it fails on a code-clean
  commit, verify with a local `npm run build` and check the post-merge build on
  main.
- Pure refactors: pixel-identical is the acceptance test, verified with a
  dangling-ref grep.
- Every commit authored solely by Jose-Gael-Cruz-Lopez — no Co-Authored-By, no
  AI trailers.
- Lead check-ins with the outcome in plain sentences, not working shorthand.
  Session length is never a reason to stop, summarize, or suggest a new session.
