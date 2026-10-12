# Audit: saplinglearn.com — SEO, AI-readability, compliance, accessibility

**Audited at:** `main @ f852e11` (2026-10-12), branch `claude/saplinglearn-seo-compliance-audit-h8s01s`.
**Method.** Six read-only sweeps (SEO, landing performance, data inventory, sharing/deletion,
legal/claims, accessibility), each citing `file:line`; a local production build
(`next build` + `next start`) for every claim about server HTML; the backend unit tests for
deletion/export/visibility (57 passed). **Not checked:** anything live on saplinglearn.com — the
sandbox egress proxy refuses that host (CONNECT 403 for every user agent), so live robots.txt,
Cloudflare bot rules and response headers are listed under *team to verify*. No production DB
access (the Supabase MCP failed to connect), so nothing here is measured against real rows.

Severity: **P0** wrong today and user-facing / legal exposure · **P1** should fix before wider
launch · **P2** hygiene.

---

## 1. SEO and AI-readability

| # | Finding | Sev | Status |
|---|---|---|---|
| S1 | `/faq`, `/gallery`, `/news`, `/wiki` emitted `<link rel="canonical" href="https://saplinglearn.com">` — Next merges metadata per top-level key, so pages without `alternates` inherited the root's `'/'`. Search engines were told each is a duplicate of home. Every route also shared the home og:title/og:url. | P0 | **Fixed** (`lib/seo/pageMetadata.ts`) |
| S2 | Sitemap listed 5 URLs; missing `/faq`, `/wiki`, `/gallery`, `/news` and all 7 `/news/*` posts; no `lastmod`. All 5 listed pages existed (none to remove). | P0 | **Fixed** — 16 URLs, lastmod from post dates / legal date |
| S3 | No structured data anywhere (0 `ld+json` blocks across 10 routes). | P1 | **Fixed** — Organization + WebSite + FAQPage on `/`, FAQPage on `/faq`, BlogPosting on posts |
| S4 | Server HTML of `/` began `SaplingLOADING000Sapling…`: the intro overlay (`IntroOverlay.tsx`) server-renders "LOADING" + the zero-padded counter. | P1 | **Fixed** — readout is CSS generated content |
| S5 | Duplicated sections in server HTML: gallery marquee rendered every card twice (`useTrackCopies` initial 2); ingest heading + pitch rendered for phone and desktop (`ActIngest.tsx`). | P1 | **Fixed** — clones added on mount; phone twin mounts only on phones |
| S6 | Hero `<h1>` server-rendered as `<span> </span>` (text scrambles in on the client). | P1 | **Fixed** — server renders final text; still invisible until the intro ends (see P-L1) |
| S7 | No `/llms.txt`. | P2 | **Fixed** — generated, links About/FAQ/Wiki/Journal/policies |
| S8 | `/faq`, `/gallery`, `/news` were `'use client'` pages, so they could not export metadata. | P1 | **Fixed** — thin server `page.tsx` wrappers |
| S9 | robots.txt (from `app/robots.ts`): one `User-agent: *` group, `Allow: /`, app routes disallowed. Nothing in the repo blocks OAI-SearchBot, ChatGPT-User, PerplexityBot, Claude-SearchBot or Claude-User. Middleware only matches app routes and does no UA filtering; no `X-Robots-Tag`, no `_headers`. | — | OK in repo; unit test now pins it |
| S10 | **Cannot verify from here:** Cloudflare dashboard settings that act outside the repo — *Bot Fight Mode*, *AI Crawl Control / Block AI bots*, *Managed robots.txt* (prepends `Disallow` lines for AI crawlers to the served robots.txt), WAF custom rules. | P0 if on | **Team to verify** (§6) |
| S11 | Only one OG image (`/og.png`) for all routes; posts use it unless they have a photo. | P2 | Posts with photos now use them; per-route images skipped |
| S12 | Body text appears twice in raw HTML on server-component pages (DOM + RSC payload `self.__next_f.push`). Normal Next.js; only affects scrapers that keep `<script>`. | — | No action |

## 2. Data inventory (who holds what)

**Collected and where** (all in Supabase Postgres unless noted; app-layer AES-256-GCM via
`services/encryption.py`, one env key, no rotation):

| Data | Encrypted at app layer | Plaintext | Notes |
|---|---|---|---|
| Google identity | email, name, first/last name | google_id (also the PK `user_{google_id}`, so it appears in URLs/logs), avatar_url | re-copied from Google every sign-in |
| OAuth tokens | access + refresh token | — | refresh token stored for **every** user (`prompt=consent, access_type=offline`) |
| Profile/onboarding | bio, location | school, year, majors, minors, learning style, username | |
| Documents | extracted_text, summary, concept_notes | file_name, category, shareability | **raw file bytes never stored**; optional Redis cache holds plaintext extracted text 30 days (only if `REDIS_URL`) |
| RAG chunks | chunk_text | embedding (768-d), doc_id, uploader_id | shared rows readable by classmates (§3) |
| Notes | title, body, last_summary | tags | |
| Tutor chat | messages.content, sessions.summary_json | topic, name, graph_update_json | |
| Knowledge graph | — | concept names, mastery, mastery events | |
| Quiz | questions_json, answers_json, context_json | scores, difficulty; per-student mistakes copied **plaintext** into class-level `offering_concept_stats` | |
| Flashcards / study guides | front/back; content | — | |
| Gradebook | notes, points | assignment title, dates | |
| Gradescope | email, password, cookies | — | BU SSO path types the BU password into shib.bu.edu + Duo push |
| Social | room message text, room summaries | room_messages.user_name (client-supplied), chat images in **public** bucket | |
| Feedback / issues | comment/topic/description | screenshots (private bucket) | |
| Job applicants | — | **all fields plaintext**; resumes in private bucket | policy promises ≤12 months; no job enforces it |
| Newsletter / waitlist | — | email (plaintext by ADR 0026) | no consent timestamp/source/unsubscribe flag |
| Telemetry | — | `events`, `llm_usage` (user_id, tokens, cost; no prompt text) | no FK to users, kept forever |
| Cookies | — | `sapling_session` (HttpOnly, 30 d), OAuth state cookies, localStorage `sapling_user` | **no third-party or analytics cookies** |

**Third parties receiving user data**

| Service | What | Notes |
|---|---|---|
| Google Gemini **Developer API** (API key, not Vertex) | full document text, notes, tutor history, RAG chunks (incl. classmates' shared chunks), quiz data incl. student name, **study-room members' full names + mastery**, embeddings of every chunk/query | tier = whatever billing the key's Cloud project has (§3.1) |
| Supabase | everything (DB + Storage); browser talks to it directly for Realtime and chat-image upload | prod region not in repo |
| Google OAuth + Calendar | sign-in requests `openid email profile calendar.events calendar.readonly` for **everyone** | calendar data is not stored and never reaches Gemini |
| Gradescope / BU IdP / Duo | user's Gradescope or BU credentials (opt-in) | unofficial client |
| Quizlet | server fetches a user-supplied public URL | |
| Railway (backend host), Cloudflare (frontend Workers, observability on) | request logs; paths contain user ids; uvicorn access log includes query strings | retention per their dashboards |
| Logfire, Recost, Redis, DBOS | only when their env vars are set | Logfire scrubber truncates prompts to 80 chars but structured outputs/tool args may pass through (verify a trace) |
| Email provider | **none in code** — no email is ever sent | see §4 |
| Analytics | **none** (no GA/PostHog/Sentry/etc.) | |
| Ko-fi | outbound link only | |

**Possible RLS gap (verify live):** RLS was applied to prod out-of-band (`docs/security/rls-lockdown-plan.md`); migrations after that date never `ENABLE ROW LEVEL SECURITY`, and Supabase grants `anon` by default. `events`, `llm_usage`, `quiz_responses`, `xp_events`, `friendships`, `friend_requests`, `course_chunk_contributors` may be readable with the public anon key. The plan's own check query settles it.

## 3. Compliance findings

### 3.1 Gemini tier, training, age — **P0, team decision**
- Calls go to the Gemini Developer API with `GEMINI_API_KEY` (`agents/_providers.py:104-109`, `services/rag_service.py:47-50`). Under the Gemini API Additional Terms, **Unpaid Services** prompts/responses may be used to improve Google's products and be read by human reviewers; **Paid Services** (Cloud Billing on) are not used to improve products. ADR 0001 says billing "must be enabled before agents go to prod" — the repo cannot prove it is.
- The claims "never sold or used to train outside models" (FAQ, wiki) and "We do not use your uploaded materials to train AI models" (Terms) are true **only if every key that sees real data is on a paid project**.
- **Age:** the Gemini API terms require users to be 18+ and bar clients "directed towards or likely to be accessed by" under-18s. Terms allowed 13+ with parental consent. This conflicts regardless of tier.
- **Fixed:** Terms minimum age is 18 and sign-in asks the user to confirm it; the policy names Gemini and states the paid-tier basis of the no-training claim. **Team must confirm billing before this ships** (§6.1).

### 3.2 Shared per-course retrieval — **P0**
- `user_settings.share_class_context` defaults **true**; no signup/onboarding step writes it, and a missing row counts as opted in (`chunk_visibility.py:143-144`). **Opt-out in practice.**
- What is shared: chunks of uploads the classifier labels `course_material` at ≥0.6 confidence. `completed_work` and `personal_notes` stay private; every unknown resolves private. The pool spans every offering/term of the course code. Shared chunk text goes into classmates' tutor and quiz prompts (no attribution, no verbatim display panel).
- **Disclosure:** the privacy policy never mentions it ("class-wide data … is anonymized"); the only control is a "Class intel" pill on the Learn screen whose tooltip says "anonymized class-level patterns"; Terms' licence covered processing "solely … to you". The landing page *does* advertise it ("every student who adds their documents makes the AI understand the course better").
- **No enrollment check:** any approved user can read any course's shared pool by naming its id in start-session.
- **Fixed (disclosure):** the privacy policy (§4), the Terms licence (§4), both FAQs, the wiki, the landing ingest copy and the in-app Class Intel tooltip now say plainly what is shared, that it is on by default, and how to turn it off. **Not changed:** the opt-out default and the missing enrollment check (§6.3). **Team decision:** keep opt-out or switch to opt-in (§6); add an onboarding/upload prompt and a Settings toggle.

### 3.3 Deletion — **P0**
- **Document delete** (`DELETE /api/documents/doc/{id}`) only sets `documents.deleted_at`. Its `course_chunks` rows (text + embeddings) are never removed, and `match_course_chunks` does not check the document — **a deleted document keeps answering the owner's tutor, and its shared chunks keep reaching classmates.** No test covers chunk removal.
- **Account delete** (`DELETE /api/profile/{id}/account`) only sets `users.deleted_at`, which nothing reads: signing in again restores the account with all data; existing session cookies stay valid (stateless, 30 days); the Google refresh token is never revoked. The UI promises "Permanently delete your account and all data. This cannot be undone."
- **Export** returns only identity/settings/roles/achievements/cosmetics; the UI promises "sessions, notes, and knowledge graph" and the wiki "everything Sapling holds on you".
- **Fixed:** `services/document_deletion.py` deletes a document's private chunks, releases its shared chunks (deleting any left with no contributor), and clears the document's text; `services/account_deletion.py` hard-deletes the account (Google token revoked, chunks withdrawn, rooms handed on or deleted, files removed, telemetry anonymised) and a pending deletion is finished at the next sign-in instead of restored. **Not changed:** the export is still partial — the policy and Settings now say so and offer a full copy by email (§6.11).

### 3.4 Legal pages
Privacy (last updated May 3 2026) and Terms were missing: Gemini as the processor of uploads and the training/tier basis, shared retrieval, Google API Services User Data Policy **Limited Use** statement, calendar scopes being requested at sign-in, Gradescope credentials, retention, real deletion/export behaviour, cookies, user rights, minimum age that matches the provider, user responsibility for rights in uploaded course materials, a takedown/copyright contact, governing law, business/contact details. Contact was `careers@` only. **Fixed:** both rewritten to match the code as it stands after this branch (effective 2026-10-12).

### 3.5 Journal / newsletter email — **P1**
- **No email is sent by the code** (no provider, template, unsubscribe link, `List-Unsubscribe` header or postal address). Yet the site promises "one letter a month", "we will tell you which group you are in", and "We'll email you once an admin lets you in".
- Subscribe forms bundle waitlist + newsletter in one consent and linked neither Privacy nor Terms.
- **Fixed:** both forms link Terms + Privacy and say how to unsubscribe; the sign-in error copy no longer promises an approval email. **Not changed:** there is still no sending code to put an unsubscribe link in (§6.6). **Team:** whatever tool sends the Journal must add an unsubscribe link and a postal address (CAN-SPAM) — or adopt a provider that does it automatically.

### 3.6 Unsupported claims — **P1**
Contradicted by the product's own wiki and code (**fixed in copy** unless noted):
- **Spaced repetition** ("ten minutes, a day, four days … Sapling schedules") — the wiki says "There is no review schedule yet"; the rating handler stores no interval. Includes the Journal post *What spacing actually buys you*, which says the intervals "shipped".
- **Quiz difficulty re-tunes after every answer** — adaptive difficulty is chosen once per quiz.
- **Study guides weighted to weak concepts** — the wiki says they are not yet.
- **Tutor cites sources / "with the sources shown"** — no filename/page reaches the model.
- **"Flag it in one click and the tutor corrects course"**, **shared room quizzes**, **office hours placed**, **study blocks around weakest concepts**, **Gradescope scores "pull themselves in"** (manual sync), **concepts extracted "as you write"**, **course planner** (a "Coming soon" screen shown as shipped).
- **"Delete a document and its data goes with it"**, **"export everything"**, **"used only to build your graph"**, **"anonymously"** in study rooms (names and graphs are visible).
- Absolutes enforced only by prompt ("never hands you the answer", "works only from your class's material") softened.
- Team size: "four of us" in five places vs five people on About.
- **Not changed, team to document:** the two BU-awards claims on About, and an explicit "not affiliated with Boston University" line (added to Terms).

### 3.7 Signup
SignInModal already says "By signing in, you agree to the terms and privacy policy" with links (browsewrap). Gaps: no age attestation; middleware sends signed-out visitors on app routes straight to Google OAuth, bypassing the notice; companion pages' "Sign In" goes to `/?signin=1`, which nothing reads; onboarding has no Terms/Privacy link. Calendar scopes are bundled into sign-in with no explanation.

## 4. Accessibility (basics)

Highest-impact, all on the public site:
- **Keyboard:** gallery cards (the 8 feature demos) cannot be focused or opened; Escape does not exit landing graph explore mode; careers resume upload is a `<div onClick>` over a `display:none` input (required field → keyboard users cannot apply); inline `outline:none` with no replacement on the wiki and news search inputs and the Journal email field.
- **Graph:** landing graph canvas has no text alternative; in-app 2D/3D graphs do have a hidden node list (good) but generic labels.
- **Carousel/motion:** gallery rails drift forever with no pause and ignore `prefers-reduced-motion`; the landing engine has no reduced-motion handling (graph rotation, ambient drift, floating cards), and the intro + scramble always run.
- **Contrast:** companion accent `#2D8F5C` as small text is 3.58:1 on paper; landing small labels `#9AA5A0`/`#8B9891`/`#B4BEB8` are 1.9–2.9:1; BetaModal greys/red fail; legal-page links are not underlined and 2.76:1 against body text.
- **Structure:** no `<main>`/skip link on landing or companion pages; collapsed FAQ answers still in the accessibility tree; decorative canvas/cards/art not `aria-hidden`; logo alts duplicate adjacent "Sapling" text; BetaModal adds a second `<h1>`.
- **Forms:** careers form labels not tied to inputs; Beta email is `type="text"`; errors not linked to fields.

---

## 5. Change log (this branch)

Written before the changes and updated as each landed. Each commit message on
`claude/saplinglearn-seo-compliance-audit-h8s01s` states what it changes and how it was verified.

| Commit | Area |
|---|---|
| `feat(seo)` | sitemap, per-route canonicals/OG, JSON-LD, `/llms.txt`, deduplicated server HTML |
| `docs(audit)` | this report and the performance/cost plan |
| `perf(frontend)` | prefetch auth calls, `/api/users`, font preloads, images, polling, concept-description cache |
| `perf(backend)` | event-loop blocking, N+1s, mastery-history truncation, keep-alive, `db=N/Xms` |
| `fix(privacy)` | document and account deletion |
| `docs(legal)` | Privacy Policy, Terms, signup/Journal consent, unsupported claims |
| `fix(a11y)` | keyboard, focus, landmarks, motion, contrast |

**Accessibility (§4) — fixed:** focus rings, Escape out of explore mode, a keyboard route into the
feature lab plus real dialog semantics, keyboard-operable careers upload and tied labels, reduced-
motion rails, skip links and `<main>`, FAQ accordions, heading levels, decorative `aria-hidden`, logo
alts, graph zoom labels, accent-text and modal contrast. **Not done:** a text alternative / node list
for the *landing* graph canvas, engine-wide reduced motion (graph rotation, ambient drift, floating
cards), the News category listbox (→ native `<select>`), the remaining sub-4.5:1 labels inside the
decorative landing illustrations, and the in-app 2D graph's tier/mastery text in its hidden list.

## 6. Needs a team decision / verification

1. **Gemini billing.** Confirm the Cloud project behind every `GEMINI_API_KEY` that sees real data (prod, staging, any dev key) has billing enabled and shows as paid tier in AI Studio; keep evidence. Until then the "not used to train" statements are conditional. Alternative: move to Vertex AI.
2. **Minimum age 18.** Set to 18 here to satisfy the Gemini API terms. If the team wants under-18 BU students, that requires a different provider arrangement (e.g. Vertex AI with its own terms review) — not a copy change.
3. **Shared retrieval consent.** Keep opt-out with disclosure (current state + new copy), or switch the default to opt-in (migration + onboarding prompt). Also: add an enrollment check before shared retrieval.
4. **Cloudflare dashboard.** Check Security → Bots (Bot Fight Mode / Super Bot Fight Mode), AI Crawl Control ("Block AI bots"), and *Managed robots.txt*; confirm `curl -A "OAI-SearchBot" https://saplinglearn.com/` and the same for ChatGPT-User, PerplexityBot, Claude-SearchBot, Claude-User return 200 and that the served robots.txt matches `app/robots.ts`.
5. **Business/contact details.** The Terms and Privacy pages name the operator as "the Sapling team" and use `careers@saplinglearn.com` (`lib/contact.ts`). Fill in the legal entity name, a postal address (also required in marketing email), and preferably a `privacy@`/`legal@` alias. Governing law is set to Massachusetts — confirm. For DMCA safe harbor, register a designated agent with the U.S. Copyright Office; the Terms' takedown section points at the contact email until then.
6. **Newsletter tooling.** Pick how the Journal is sent; it must carry an unsubscribe link and postal address.
7. **RLS.** Run the check in `docs/security/rls-lockdown-plan.md` against prod.
8. **Calendar scopes.** Ask for Calendar only when the user connects it, and drop `calendar.readonly` if `events.list` on `primary` works with `calendar.events` alone; this also simplifies Google OAuth verification.
9. **Names in prompts.** Study-room summaries send every member's full name to Gemini; quiz context sends the student's name. Consider first names or none.
10. **BU awards and naming.** Keep documentation for the two award claims on /about.
11. **Full data export.** Settings exports only profile-level data; the policy promises a complete copy on request by email. Either build the full export (every user-keyed table, decrypted) or keep the manual process documented.
12. **Stale sessions after deletion.** Session tokens are stateless (30 days). After an account is deleted, a still-open tab elsewhere can create an empty stub `users` row via `ensure_user_exists` (no personal data, and the next sign-in adopts it). A per-user token epoch would close this.
13. **Journal post edits.** Four posts were edited for accuracy (each now carries `updatedAt: 2026-10-12`), and *What spacing actually buys you* gained an editor's note that the scheduler has not shipped. Review the wording; the alternative is unpublishing that post.
