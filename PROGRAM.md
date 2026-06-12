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

## Backlog / known items

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
