# Inventory — public / pre-auth pages

Paths relative to `frontend/src/`. Routes (`app/(public)/`): `/`, `/about`, `/careers`, `/careers/[slug]`, `/faq`, `/gallery`, `/news`, `/news/[slug]`, `/privacy`, `/terms`, `/wiki`. No `/team`, no `not-found.tsx` (404 = Next default, unbranded).

## Design systems
- **Landing `/` (cool):** root `.landing-dc.landing-v5` (`app/(public)/page.tsx:86`), ground `#f2f4f0`; `--ld-*` tokens `globals.css:2487-2530` (deep `#445D22`, bright `#68951F`, mid `#7B9E51`, pale `#B1D28B`, coral `#E27A63`, ink `#191F13`, muted `#697062`). Hero also carries `.landing-page` (mesh, `.liquid-glass`, marketing tokens `globals.css:1216, 1425-1550`). Tier colours `lib/landing/course.ts:26`; feature-lab tier palette differs (`lab/LabShell.tsx:15`). Nav theme `landing-v5/navTheme.ts:38`.
- **Other public pages (warm paper):** `components/companion/CompanionShell.tsx` — ground `#f4f1ea`, ink `#1a1814`, body `#3f3b31`, muted `#6f6857`, accent `#597536`, footer `#faf8f3`, CTA `#445D22`. Type: `lib/landing/companionType.ts` (Plex Mono, Aleo). `.cp-*` hovers + `fadeUp` ~`globals.css:2950`. Brand tokens `globals.css:16-38`.
- Fonts: SUSE, Aleo, IBM Plex Mono, Caveat, Inter (hero).
- Legacy: `components/landing/**` only `useLanding.ts` + `anim/FadeIn`; `components/marketing/**` only `SignInModal.tsx` + `HeroCard.tsx`.

**Breakpoints:** ≤1023 hero cards + drag field hidden · ≤899 gallery note hidden, `--gal-scale` .84, wiki rail collapses · ≤900 grids stack (ingest, tutor, FAQ, journal 2-col, lab) · ≤640 phone pass (nav tight, explore inspector → bottom sheet, tutor trimmed, **#gallery hidden**, journal 1-col, newsletter stacks, beta modal right col only) · ≤599 `--gal-scale` .68. (`globals.css:2536-2950`; `e2e/landing-mobile.spec.ts` 390×664.)

**Determinism:** `NEXT_PUBLIC_TEST_MODE` / reduced motion parks the hero on a static frame (`Hero.tsx:99, 291`); intro holds 1900ms. Testids only on SignInModal (`signin-modal`, `-close`, `-error`, `-google-button`, `-cancel`) + `error-fallback`.

## `/` Landing — sections top→bottom
Ambient canvas · IntroOverlay · fixed Navbar · Hero · descent band · Act I `#act-graph` (460vh sticky) · RiseBand · phone `.ld-ingest-intro` · Act II `#act-ingest` (320vh) · Act III `#act-tutor` (340vh) · `#gallery` (2 marquee rails, 8 cards) · `#faq` (8 Q&A, `lib/landing/content.ts:149`) · `#newsletter` (3 journal cards + panel) · `#cta` · Footer. Overlays: SignInModal, BetaModal, FeatureLab.

| State id | What the user sees | Trigger | File:line | Anchors |
|---|---|---|---|---|
| landing/intro-loading | sprout animation, wordmark, `LOADING 000→100` | 0–1.9s | landing-v5/IntroOverlay.tsx:32, 118 | – |
| landing/hero-scrambling | letters scramble, nav slides in | 1.9–3.4s | useLanding.ts:310-357 | h1[aria-label=Sapling] |
| landing/hero-rest | "Sapling", "Grow Your Knowledge", lede, Beta CTA, cue, point cloud, 2 glass cards | ~3.5s | Hero.tsx:325-460 | .floating-card |
| landing/hero-rest-tablet-phone | no floating cards | < 1024 / ≤640 | globals.css:2536 | – |
| landing/nav-visible / -hidden / -hover | wordmark + Sign In + Get Started / off-screen / hover | scroll | Navbar.tsx:62-112; useLanding.ts:274 | .sapling-nav |
| landing/act-graph-cap0..cap3-closing | "A hundred names you don't know yet." → "You study. They connect." → "Mastery is the color." + legend → "See what you know." + orbit hint | scroll | ActGraph.tsx:28-225 | [data-cap], [data-tick] |
| landing/act-graph-orbit-drag | rotate | drag | useLanding.ts:485-510 | – |
| landing/explore-idle / -node-hover / -node-selected / -node-selected-phone / -zoomed | HUD (course, legend, hint, ✕ EXIT EXPLORE) / pointer / inspector (tier, blurb, mastery, chips, Quiz me / Ask the tutor) / bottom sheet / 0.3–3× | click canvas after act ends | ActGraph.tsx:233-342 | .ld-hud, .ld-hud-inspector |
| landing/ingest-intro-phone | heading above act | ≤640 | ActIngest.tsx:136 | – |
| landing/act-ingest-start / -flying / -end | "Drop in the whole course.", syllabus doc, 4 tiles +0 → chips flying → +3 each | scroll | ActIngest.tsx:141-290 | [data-ingest-tile], [data-chip] |
| landing/act-tutor-socratic / -expository / -teachback / -docked-pills / -pill-* / -phone | prism faces + captions; pills after 86% | scroll / click pill | ActTutor.tsx:81-256 | [data-panel], [data-tutor-pills] |
| landing/gallery-rest / -card-hover / -dragging / -tablet / -hidden-phone | "The rest of the grove." + hand note + 2 rails | scroll | Gallery.tsx:264-377 | [data-tk], .ld-galcard |
| landing/lab-{quiz,flashcards,notetaker,guide,rooms,gradebook,calendar,tutor} / -switching / -tablet | FLIP-grown panel: kicker, title, bullets, browser-chrome demo, 8-tool rail, close | gallery card / explore buttons | FeatureLab.tsx:42-117; lab/* | [data-rail], .ld-labclose |
| lab/quiz-* · cards-* · notes-* · guide-* · rooms-* · grades-* · calendar-* · tutor-* | interactive demo sub-states (see `lab/*Demo.tsx`) | interact | lab/QuizDemo.tsx … TutorDemo.tsx | – |
| landing/faq-default / -item-n-open / -all-closed / -phone | sticky intro + accordion item 0 open | click | Faq.tsx:41-126 | button[aria-expanded] |
| landing/journal-rest / -card-hover | 3 article cards | scroll | Journal.tsx:45-88 | .ld-post |
| landing/newsletter-idle / -focus / -invalid-noop / -submitting / -error / -success / -phone | "Get the Journal…" email + Join → "Signing you up…" → red error / "You're on the tree." | submit | Journal.tsx:97-150; useLanding.ts:631-643 | .ld-newsletter |
| landing/cta | "Ready to Start Growing?" + Beta button | scroll | Closing.tsx:33-72 | #cta |
| landing/footer | links (no Careers) | bottom | Closing.tsx:90-108 | .ld-footer |
| landing/beta-modal-form / -validation / -submitting / -error / -success / -phone / -closing | 2-col card, waitlist form → "Planting your node…" → "You're on the waitlist." | Beta CTA | BetaModal.tsx:72-285 | .ld-betacard |
| landing/signin-modal-idle / -waiting / -error-{not_approved,invalid_domain,signin_failed,session_expired,oauth_denied,env_misconfig,revoked,google_not_configured,unknown} / -redirect-same-tab | "Welcome back." + Continue with Google → "Waiting for Google…" + Cancel → red box | nav Sign In | marketing/SignInModal.tsx:14-357 | signin-* |

## Companion shell (all non-landing pages)
shell/header (sticky blurred: wordmark, Sign In, Get Started) · shell/header-hover · shell/footer (incl. Careers; current page bold) — `CompanionShell.tsx:82-168`. No mobile menu anywhere.

## Other pages
| State id | What the user sees | Trigger | File:line |
|---|---|---|---|
| about/default / narrow | essay, "Meet the team" (5), How we work, Recognition / 1-col team | visit / < 560 | about/page.tsx:80-199 |
| careers/not-hiring (live) | "Not hiring right now", empty openings, mailto call-out | visit (`JOBS = []`) | careers/CareersList.tsx:57-231 |
| careers/hiring-list / role-expanded (hypothetical) | role rows / expanded + Apply | needs JOBS data | CareersList.tsx:89-218 |
| careers-slug/404 (live) | Next 404 | any slug | careers/[slug]/page.tsx:81 |
| careers-slug/form-idle / dropzone-dragover / resume-attached / native-required / error-no-resume / submitting / submit-error / success (hypothetical) | Apply form states | needs JOBS data | ApplyForm.tsx:130-445 |
| faq/default / item-n-open / all-closed | 3 groups × 4, first open | click | faq/page.tsx:31-86 |
| gallery/all / filter-{learn,study,together,semester} / shot-hover / lightbox-open / lightbox-closing | 12 shots (3/4/2/3 per filter) / lightbox | click | gallery/page.tsx:28-95; companion/Lightbox.tsx:113-170 |
| news/default / search-typing / menu-open / menu-item-hover / filter-{release,product,perspective,founding} / empty / card-hover | 7 cards; search; category listbox (2/2/2/1); "Nothing matches…" + Clear | interact | news/page.tsx:42-206 |
| news-slug/article-photo / article-motif-{canopy,graph,teachback,spacing,syllabus} / 404 | article layout | slug | news/[slug]/page.tsx:82-131; journal/ArticleArt.tsx |
| privacy/default / terms/default | Legal, last updated, 10 / 12 clause rows | visit | privacy/page.tsx:177-297; terms/page.tsx:147-220 |
| wiki/default / scrollspy-section-x / search-filtered / search-no-match / search-cleared / narrow / shot-lightbox | sticky 18-link rail + sections + figures | scroll / search | wiki/page.tsx:155-511; WikiRail.tsx:81-195; WikiSearch.tsx:101-118 |
| global/404 / global/error | Next default / ErrorFallback | – | app/error.tsx |

## Transitions
Intro → scramble → hero · nav wordmark → top; Get Started → #cta; Sign In → signin modal → waiting → error / `/onboarding` / `/dashboard` / `/pending` · Beta CTA → beta modal → validation / submitting → success (also flips newsletter) / error · Act I caps by scroll → click → explore → node → chips / × / EXIT · Quiz me → lab-quiz, Ask the tutor → lab idx 2 · Act III faces → pills · gallery card i → lab-i ↔ rail → close · FAQ toggle; "Read the full FAQ" → /faq · newsletter submit · journal card → /news/{slug} · footer → About/Wiki/Gallery/News/FAQ/Terms/Privacy. Companion: wordmark → /, Sign In → `/?signin=1`, Get Started → `/#newsletter`; /news Subscribe → `/#newsletter`; card → slug → ← The Journal; /faq → /wiki, `/#newsletter`; /gallery tile → lightbox, Open the toolkit → `/#gallery`; /wiki rail → #section.

## Uncertain / needs a human
1. Companion "Sign In" (`/?signin=1`) doesn't open the modal (landing ignores searchParams).
2. Middleware `/?error=<code>` shows no error (errorCode not passed to SignInModal).
3. Explore "Ask the tutor" opens lab idx 2 (Notetaker), not 7 (Tutor) — likely bug (`page.tsx:165`).
4. `/#newsletter` / `/#gallery` deep links may not land (intro, scroll governor; #gallery hidden ≤640).
5. No mobile menu exists — a hamburger would be new design.
6. Landing footer lacks Careers; companion footer has it.
7. Careers empty — hiring/apply frames need agreed placeholder data.
8. 404 unbranded — design one?
9. Canvas/WebGL acts are random per load — capture as images.
10. News has 7 articles (comment says six).
11. Unverified: `galleryMinis.tsx` minis, `ArticleArt` motifs, legacy `.landing-graph-*`/`.landing-bento-*` CSS usage.
