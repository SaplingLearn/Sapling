# Plan: Sapling performance and cost

**Audited at:** `main @ f852e11` (2026-10-12). Four read-only sweeps (landing page, app routes,
backend, AI pipeline). Landing numbers are **measured** on a local production build in headless
Chromium (desktop, and "mobile" = Slow-4G + 4× CPU + 390×844). Backend round-trip counts are
**static counts from the code**, not measured — item B8 adds the counter that measures them.
LLM costs are **estimates** rebuilt from prompt sizes at list prices; no production `llm_usage`
rows were available. Items that only matter at a scale Sapling does not have yet (sharding,
multi-worker session stores, CDN tiering, explicit context caching) are left out or parked in
Tier 3.

**Status key:** ✅ done on this branch · 🔜 next · ⏸ AI pipeline — held until the team green-lights
that phase · 🧭 needs a team decision.

## Headline numbers

| Surface | Today |
|---|---|
| `/` LCP | **2.8 s desktop, 7.8 s mobile** (hero h1, gated by a 1.9 s intro timer that starts only after JS runs) |
| `/` CLS | 0.88–0.94 desktop (0.81 from the graph section collapsing on wheel scroll, 0.12 from the hero scramble) |
| `/` JS | 247 KB gz (165 KB shared baseline + ~90 KB landing; no three/d3/mermaid reach it) |
| Fonts | 19 files / 551 KB preloaded on **every** route; ~139 KB needed above the fold |
| Images | journal PNGs 1.32 MB; gallery PNGs 5.28 MB; Cloudflare has no `IMAGES` binding so `next/image` serves originals |
| Shell page load | middleware calls `/api/auth/me` (4–9 DB round trips) on every matched request **including router prefetches** — est. 35–40 calls per cold load |
| Every page | `UserProvider` fetches `/api/users` (every user's decrypted name) and nothing reads it |
| Backend | one uvicorn process; sync PostgREST client and OCR inside `async def` routes stall **all** requests, including other users' token streams |
| Achievement poll | ~30–35 sequential round trips every 60 s per open tab |
| Tutor turn | an unused Gemini Flash course-summary call + 15–70 round trips inline on most mastery-changing turns |

---

## Tier 1 — high impact, low effort

### Frontend

| # | File | Change | Expected gain | Verify | Status |
|---|---|---|---|---|---|
| F1 | `frontend/src/middleware.ts` | Exclude router prefetches from the matcher (`missing: next-router-prefetch / purpose=prefetch`). | ~35–40 fewer `/api/auth/me` calls (150–350 DB round trips) per cold shell load | count `/api/auth/me` lines in the backend log per page load; `middleware.test.ts` | ✅ |
| F2 | `frontend/src/context/UserContext.tsx` | Delete the unconditional `/api/users` fetch; nothing reads it. | −1 request on every page (public included) and stops shipping every user's name to every browser | Network panel | ✅ |
| F3 | `frontend/src/app/layout.tsx` | `preload: false` on Spectral (14 files) and Caveat. Playfair italic shares one `next/font` call with its upright face, so it stays. | **19 → 4 font preloads per page (measured in the build)**; ~400 KB less high-priority bytes | count `<link rel=preload as=font>` in built HTML | ✅ |
| F4 | `frontend/src/components/landing-v5/Hero.tsx` | Give the hero content box a fixed width so the scramble cannot resize it. | removes measured CLS 0.124 | layout-shift entries 2–4 s after load | ✅ |
| F5 | `frontend/open-next.config.ts` + `package.json` `cf:build` | Use `staticAssetsIncrementalCache` so Workers serve prerendered HTML instead of re-rendering per request (the default "dummy" cache throws on read). **The cache is only populated by `opennextjs-cloudflare deploy/upload/preview/populateCache`**; prod deploys with `wrangler versions upload`, so the build command must also run `opennextjs-cloudflare populateCache local` (a file copy into `.open-next/assets/cdn-cgi/_next_cache`). | lower TTFB on every public page; less Worker CPU | staging: `curl -w '%{time_starttransfer}'` before/after; Worker CPU graph | 🧭 not changed — pipeline change that cannot be verified from this sandbox; try on staging |
| F6 | `frontend/public/journal-*`, `public/gallery/*`, `scripts/gallery-shots.sh` | Gallery screenshots → WebP q85; journal photos → progressive JPEG q85 (they double as `og:image`, where JPEG is the safe format); the capture script converts after each capture. | **6.61 MB → 0.58 MB (measured)** | byte sizes in Network panel; `/gallery` LCP | ✅ |
| F7 | `frontend/src/lib/useAchievementUnlockWatcher.ts` + `backend/routes/profile.py` | Poll a cheap earned-ids endpoint; skip ticks while `document.hidden`. | ~30–35 → 1 round trip per poll per tab | backend log | ✅ |
| F8 | `frontend/src/components/screens/Achievements.tsx` | Fetch achievements and `/me` in parallel; drop the focus refetch. | hero card no longer waits on the heavy endpoint | Network waterfall | ✅ |
| F9 | `frontend/src/lib/api.ts` (`describeConcept`) | De-dupe in-flight calls and cache per `concept|course` for the session. | repeat concept cards are instant and cost no LLM call | `llm_usage` rows with `task=concept_describe` | ✅ |
| F10 | `useLanding.ts` / `IntroOverlay.tsx` / `Hero.tsx` | Skip the intro hold and the scramble under `prefers-reduced-motion`. | LCP ≈ FCP for reduced-motion users; WCAG 2.3.3 | Lighthouse with reduced motion emulated | ✅ |
| F11 | same | **Remove or shorten the 1.9 s intro** (or make it a pure-CSS fade that starts at first paint, not after hydration). | LCP 2.8 → ~0.5 s desktop, 7.8 → ~2–3 s mobile (est.) | Lighthouse / `scratchpad/vitals.cjs` | 🧭 design call — the intro is a deliberate lockup |

### Backend

| # | File | Change | Expected gain | Verify | Status |
|---|---|---|---|---|---|
| B1 | `backend/routes/documents.py` (`_extract_text_or_422`), `services/chat_stream.py` (`on_complete`) | Run OCR/PDF extraction and post-stream persistence in `asyncio.to_thread`. | a scanned PDF no longer freezes the whole server for seconds | test: concurrent `GET /api/health` returns fast while an upload extracts | 🔜 |
| B2 | `backend/routes/learn.py` (`list_sessions`) | One query with `messages(count)` instead of one count per session. | 11 → 1 round trips (Dashboard/Learn), 51 → 1 on Tree | `tests/test_learn_routes.py` | 🔜 |
| B3 | `backend/services/graph_service.py` (`get_courses`) | One node read grouped in Python instead of one count per course. | 1+N → 2 round trips on almost every route | unit test | 🔜 |
| B4 | `backend/services/graph_service.py` (mastery history) | Read newest events first with a bound, so PostgREST's 1000-row cap stops returning the **oldest** 1000. | correctness: velocity/"last 5" stop going stale for active users | unit test | 🔜 |
| B5 | `backend/db/connection.py` | Keep-alive 60 s, 20 connections, 15 s timeout (5 s connect). | no fresh TLS handshake to Supabase on the first call after 5 s idle (~30–150 ms) | first-call latency after 10 s idle | 🔜 |
| B6 | `backend/db/connection.py` + `services/request_context.py` | Count PostgREST round trips and time per request; append `db=N/Xms` to the request log line. | turns every estimate here into a measured number | log line | 🔜 |
| B7 | `backend/routes/learn.py` (start-session) | Stop computing `graph_state` the frontend never reads. | −6+ round trips per session start | `tests/test_learn_routes.py` | 🔜 |
| B8 | `backend/routes/auth.py` (`/me`) | One embedded select instead of 4–9 reads. | 4–9 → 1 round trip on every app mount | log counter (B6) | 🔜 Tier 2 — F1 already removes most calls |
| B9 | `services/graph_service.py:882-891` | Move `update_course_context` off the request path and drop the unused Flash summary. | −1 Flash call and −1.5–5 s on mastery-changing tutor turns / quiz submit | `llm_usage feature='course_summary'` | ⏸ touches an LLM call |

### AI pipeline (held)

| # | File | Change | Expected gain | Verify | Status |
|---|---|---|---|---|---|
| A1 | `services/course_context_service.py` | = B9: remove the course-summary call nobody reads; fix the `course_id`→`offering_id` mix-up at `documents.py:764/1097`. | ~$0.002–0.003 + seconds per mastery turn | cost query | ⏸ |
| A2 | `agents/concept_extraction.py`, `syllabus_extraction.py`, `study_guide.py`, `note_chat.py`, `ocr_vision.py` | Cap Flash thinking (budget 0–512; Pro min 128). | 30–60% of these calls' cost, seconds of latency | evals vs `baselines.json`; avg `completion_tokens` | ⏸ |
| A3 | `agents/_providers.py` (`google_model`) | Memoize per model name instead of building a client every tutor turn. | ~100–300 ms first-token | unit test | ⏸ |
| A4 | `agents/_providers.py` (`_new_provider`) | 90 s client timeout instead of the inherited 600 s. | bounded hangs | unit test | ⏸ |
| A5 | `routes/documents.py`, `agents/__init__.py` | Send the classifier only the head of the document; check length **before** the pipeline. | classifier input T → ~2k tokens; long docs stop being billed then failing | eval + `task='classifier'` tokens | ⏸ |
| A6 | `services/chat_context.py:284-320` | Wrap each document once, not each concept note. | up to ~5k tokens per document-search call | token counts | ⏸ |
| A7 | `agents/usage.py`, `llm_pricing.py`, new migration | Record cache-read tokens, thinking tokens, request/tool counts, latency; price cached tokens correctly; separate start-session/action/fallback features. | makes the rest verifiable | queries in the AI audit | ⏸ |

---

## Tier 2 — medium effort

| # | File | Change | Expected gain | Verify |
|---|---|---|---|---|
| F12 | `frontend/src/lib/landing/engine/index.ts:214-249` | Fix the graph section collapse scroll compensation (or replace the act with a static end-state on mobile/reduced-motion). | removes the 0.81 CLS window (worst desktop vital) | layout-shift entries while wheel-scrolling |
| F13 | `frontend/src/app/(public)/LandingPage.tsx` | `next/dynamic` FeatureLab + lab demos, BetaModal, SignInModal; build landing `POSTS` without article bodies. | ~25–30 KB gz off `/` | per-route bytes |
| F14 | `lib/landing/engine/*`, `Hero.tsx` | Engine-wide reduced-motion; cap hero canvas DPR at 2; static frame on coarse pointers; one floating-card loop (skip below `lg`). | mobile TBT (2.75 s measured) down | throttled trace |
| F15 | `frontend/src/components/screens/Social.tsx` | Fetch room overview only in the Overview tab; @-mention names from members. | opening /social stops running one `get_graph` per member and a possible Gemini summary | `llm_usage task=social_summary` |
| F16 | `frontend/src/lib/api.ts` | Tiny shared cache (in-flight de-dup + 60 s SWR) for `getCourses`/`getGraph`/`getSessions`, cleared on `sapling:graph-changed`. | instant paints between Dashboard/Learn/Tree/Quiz | Network panel |
| F17 | `components/chat/MarkdownChat.tsx`, `ChatPanel.tsx` | Preload the chunk on panel mount; load katex only for math and highlight only for code fences; drop `detect: true`. | plain replies need ~45 KB gz instead of 184 KB; first bubble not blank | Network panel |
| F18 | `components/screens/Learn.tsx` | Batch SSE deltas per animation frame; `useCallback` on `handleNodeClick`. | ≤20 renders/s while streaming | React Profiler |
| F19 | `Social.tsx`, `Calendar.tsx`, `Study.tsx` | `import()` supabase-js inside realtime effects (−43 KB gz /social); `LazyMotion` on Calendar (−25–38 KB); dynamic `FlashcardImportModal`. | first-load JS per route | `route-bundle-stats.json` |
| B10 | `backend/routes/learn.py` | Run the tutor's independent prep reads concurrently in threads; lru-cache course info and catalog chunk. | ~100–250 ms time-to-first-token; no event-loop stall | Logfire span |
| B11 | `backend/routes/auth.py` | = B8 embedded `/me`. | 4–9 → 1 | log counter |
| B12 | `services/academics.py`, `achievement_service.py` | lru-cache terms and achievement catalog with clear hooks in admin mutators; `_count_rows` via `select_with_count(limit=1)`; one `user_achievements` read across the 3 `check_achievements` calls. | fewer round trips on graph updates | log counter |
| B13 | `routes/social.py:91,219`, `routes/study_guide.py:220` | `room_members(count)`; don't pull every guide's encrypted content to list them. | fewer round trips / bytes | log counter |
| A8 | `services/chat_stream.py:426-433` | Try the one-request continuation before the full re-run on textless turns, or fall back to Flash. | removes a whole re-run on 25–40% of Flash-Lite turns (est.) | rerun-rate query |
| A9 | `agents/quiz.py:88-104` | Pre-fetch the three always-called tool payloads into the message: 1 request instead of 2–4. | 40–60% fewer quiz input tokens, 1.5–4 s faster | `quiz_generation` eval |
| A10 | `routes/learn.py:345` | Cap tutor history in blocks of ~10 turns (keeps the implicit-cache prefix stable). | bounded cost on long sessions | p95 `prompt_tokens` for `chat_tutor` |
| A11 | `routes/learn.py` retrieval | Skip retrieval on chit-chat; search the topic / last user message instead of boilerplate; exclude catalog rows from tutor retrieval (already injected). | fewer wasted embeddings + context tokens | token counts |
| A12 | quiz, note chat, `/learn/action`, study guide | Stream the responses that currently wait 7–10 s. | perceived latency | UX |

## Tier 3 — later, or only if measured

- Move `PENDING_SESSIONS` (`routes/learn.py:38`) to the DB **before** ever adding uvicorn workers (multiple workers would lose sessions today).
- ETag `/graph/{uid}` and `/courses` via `services/http_cache.py`.
- `Prefer: return=minimal` on write-only inserts.
- Fully async httpx client (unnecessary once B1/B10 use threads).
- Embed only chunk ids without an embedding; re-embed only failed batches on retry; cache quiz query embeddings; reuse results for an identical re-upload. (A)
- Persist AI concept descriptions server-side. (A)
- Explicit Gemini context caching — not worth it at current traffic; implicit caching already fits the tutor's prompt order. (A)
- `public/_headers` with a moderate `max-age` for un-hashed public assets.
- Delete the dead three.js hero path in `useLanding.ts:228-260` and `lib/landing/hero3d/`.

## How to get real numbers

- **Endpoints (Logfire, if `LOGFIRE_TOKEN` is set):**
  ```sql
  SELECT http_method, http_route, count(*) calls,
         approx_percentile_cont(duration,0.5)*1000 p50_ms,
         approx_percentile_cont(duration,0.95)*1000 p95_ms
  FROM records
  WHERE service_name='sapling-backend' AND http_route IS NOT NULL AND parent_span_id IS NULL
    AND start_timestamp > now() - interval '7 days'
  GROUP BY 1,2 ORDER BY calls DESC LIMIT 10;
  ```
- **Round trips per request:** the `db=N/Xms` suffix B6 adds to every request log line.
- **LLM spend per feature (last 30 days):**
  ```sql
  SELECT feature, task, model, count(*) runs, count(DISTINCT request_id) reqs,
         round(avg(prompt_tokens)) avg_in, round(avg(completion_tokens)) avg_out,
         round(sum(cost_usd),4) cost
  FROM llm_usage WHERE created_at >= now() - interval '30 days'
  GROUP BY 1,2,3 ORDER BY cost DESC NULLS LAST;
  ```
