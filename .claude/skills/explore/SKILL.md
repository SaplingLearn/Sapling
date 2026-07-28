---
name: explore
description: Run an interactive Chapter 2 exploratory-testing session of the Sapling app (#399/#403) — boots the deterministic local E2E stack, signs in a real browser as the seeded student, explores the UI for bugs with the e2e oracles as judge, and writes .explore/findings.md. Local-only; needs the stack lock. Use when asked to "explore the app", "run an exploration", or "/explore".
---

# /explore — interactive exploratory testing

You are about to become the explorer yourself, watchably, in this session —
the headless twin of this flow is `make explore`. The operator can steer you
at any point; follow their steering over the default itinerary.

## Steps

1. **Boot.** Run `scripts/explore.sh up` (takes minutes: Supabase, migrations,
   seed, backend, test-profile Next build; it takes the machine-singleton
   stack lock and fails fast if another session holds it — if it does, stop
   and tell the operator). Everything lands in `.explore/`.

2. **Open a browser you can drive.** Use this session's browser tools
   (Playwright MCP if configured, else the Claude-in-Chrome tools) on a NEW
   tab at `http://localhost:3000`.

3. **Sign in as the seeded student.** The storage-state file works only for
   Playwright contexts; in a live browser, mint the session from the page
   itself — run this JavaScript on the localhost:3000 tab, then reload:

   ```js
   await fetch("/api/auth/test-login", {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     credentials: "same-origin",
     body: JSON.stringify({ user_id: "rich-user-active" }),
   });
   localStorage.setItem(
     "sapling_user",
     JSON.stringify({ id: "rich-user-active", name: "Rich Active", avatar: "" })
   );
   location.reload();
   ```

   (Both halves are required — the cookie alone leaves the dashboard on an
   infinite skeleton, bug #430.)

4. **Explore.** Read `scripts/explore/explorer-prompt.md` and follow it as
   your mission briefing: the persona, the break-things mandate, the
   report-never-fix rule, the oracle cadence
   (`cd backend && venv/bin/python -m e2e_oracles` after each major flow),
   and the findings format. Append findings to `.explore/findings.md` as you
   go, and narrate what you're trying so the operator can steer.

5. **Finish.** Run `scripts/explore.sh down` — it runs the oracle final pass,
   appends it to `.explore/findings.md`, tears the stack down, and releases
   the lock. Then summarize the findings for the operator and point them at
   `docs/e2e-exploration.md` for triage/promotion.

## Hard rules

- Never skip step 5, even after errors — the stack and lock must not leak.
- Report, never fix: no app-code edits, no git, no writes outside `.explore/`.
- If the browser tools can't reach localhost:3000, check `.e2e/*.log`, report,
  and tear down — don't debug the stack mid-exploration.
