# Sapling — Claude Code Guidelines

## Project Overview

Sapling is an AI-powered study companion. It has two services:

- **Frontend** — Next.js (TypeScript), lives in `frontend/`
- **Backend** — FastAPI (Python), lives in `backend/`

## Directory Structure

```
sapling/
├── CLAUDE.md                                          # Claude Code guidelines and project conventions
├── README.md                                          # Project overview and setup instructions
├── docker-compose.yml                                 # Orchestrates frontend + backend containers
├── landingpage.png                                    # Screenshot of the landing page
├── .impeccable.md                                     # Impeccable design skill configuration
│
├── backend/
│   ├── main.py                                        # FastAPI app entry point, registers all routers
│   ├── config.py                                      # Loads and validates env vars (Supabase, Gemini, etc.)
│   ├── requirements.txt                               # Python dependencies
│   ├── Dockerfile                                     # Backend container image definition
│   ├── .dockerignore                                  # Files excluded from the Docker build context
│   ├── .env                                           # Local secrets (not committed)
│   ├── .env.example                                   # Template showing required env vars
│   │
│   ├── db/
│   │   ├── connection.py                              # Creates and exports the Supabase client
│   │   ├── supabase_schema.sql                        # Full Supabase table/index schema
│   │   ├── seed.sql                                   # Sample data for local development
│   │   ├── migration_google_auth.sql                  # Migration adding Google OAuth user fields
│   │   ├── migration_add_is_approved.sql              # Migration adding user approval gate flag
│   │   ├── migration_onboarding_fields.sql            # Migration adding onboarding profile columns
│   │   ├── migration_roles.sql                        # Migration adding roles and user_roles tables
│   │   ├── migration_achievements.sql                 # Migration adding achievements, triggers, and user_achievements
│   │   ├── migration_cosmetics.sql                    # Migration adding cosmetics and user_cosmetics tables
│   │   ├── migration_profile_settings.sql             # Migration adding profile and settings fields
│   │   ├── migration_concept_notes.sql                # Migration adding concept_notes column to documents
│   │   ├── migration_newsletter.sql                   # Migration adding newsletter_subscribers table
│   │   ├── migration_flashcard_course_id.sql          # Migration adding course_id to flashcards
│   │   ├── migration_gradebook.sql                    # Migration adding gradebook tables (categories, assignments, letter scales)
│   │   ├── migration_drop_legacy_grade_tables.sql     # Cleanup migration removing legacy grade_* tables
│   │   ├── migration_encryption_text_columns.sql      # Retypes encrypted columns to TEXT to fit AES-256-GCM ciphertext
│   │   ├── backfill_encryption.py                     # One-shot script that walks rows + encrypts existing plaintext
│   │   ├── dedup_nodes.py                             # One-off script to deduplicate knowledge graph nodes
│   │   └── archive/                                   # Old pre-Supabase init scripts (no longer used)
│   │
│   ├── models/
│   │   └── __init__.py                                # Pydantic request/response models package init
│   │
│   ├── prompts/
│   │   ├── preamble.txt                               # System preamble injected into every AI session
│   │   ├── socratic.txt                               # Prompt for Socratic questioning study mode
│   │   ├── teachback.txt                              # Prompt for teach-back (explain-it-back) mode
│   │   ├── expository.txt                             # Prompt for direct expository explanation mode
│   │   ├── quiz_generation.txt                        # Prompt for generating quiz questions from content
│   │   ├── quiz_context_update.txt                    # Prompt for updating quiz state after each answer
│   │   ├── study_match.txt                            # Prompt for matching students into study groups
│   │   ├── syllabus_extraction.txt                    # Prompt for extracting assignments + grading categories from a syllabus
│   │   └── shared_context.txt                         # Prompt fragment injected when shared course context is on
│   │
│   ├── routes/
│   │   ├── admin.py                                   # Admin endpoints for role, achievement, cosmetic, and user management
│   │   ├── auth.py                                    # Google OAuth sign-in (popup flow), session tokens, and user upsert
│   │   ├── calendar.py                                # Endpoints to read and sync assignment calendar events
│   │   ├── careers.py                                 # Endpoints for job listings and application submission
│   │   ├── documents.py                               # Upload, classify, summarize, and extract from docs
│   │   ├── extract.py                                 # OCR and text extraction pipeline for uploaded files
│   │   ├── feedback.py                                # Endpoints to submit session and general user feedback
│   │   ├── flashcards.py                              # CRUD endpoints for user flashcard decks
│   │   ├── gradebook.py                               # Gradebook endpoints (courses, categories, assignments, letter scales, syllabus apply)
│   │   ├── graph.py                                   # Endpoints to build and query the knowledge graph
│   │   ├── learn.py                                   # Streaming AI tutoring chat endpoint (SSE)
│   │   ├── newsletter.py                              # Newsletter / beta-list signup endpoint
│   │   ├── onboarding.py                              # Course search and onboarding profile submission
│   │   ├── profile.py                                 # Public profiles, settings, cosmetics, achievements, account mgmt
│   │   ├── quiz.py                                    # Quiz session creation, answering, and scoring endpoints
│   │   ├── social.py                                  # Study room creation, membership, and chat endpoints
│   │   └── study_guide.py                             # Endpoint to generate a structured study guide from docs
│   │
│   ├── services/
│   │   ├── achievement_service.py                     # Checks and grants achievements when event thresholds are met
│   │   ├── assignment_dedupe.py                       # Deduplicates assignments before inserting into DB
│   │   ├── auth_guard.py                              # HMAC session token verification and role-based route guards
│   │   ├── calendar_service.py                        # Formats and writes assignments as calendar events
│   │   ├── course_context_service.py                  # Fetches and caches shared course context for a session
│   │   ├── encryption.py                              # AES-256-GCM helpers (encrypt / decrypt / *_if_present) for column-level encryption
│   │   ├── extraction_service.py                      # Thin router selecting an OCR backend based on OCR_ENGINE env var
│   │   ├── extraction_backends/                       # OCR engine implementations (docling, GOT-OCR 2.0, tesseract)
│   │   ├── flashcard_import_service.py                # Parses + AI-extracts flashcards from paste, file, URL, photo
│   │   ├── gemini_service.py                          # Wrapper around the Gemini API (chat, streaming, model selection)
│   │   ├── gradebook_service.py                       # Grade calculations: category_grade, current_grade, letter_for
│   │   ├── graph_service.py                           # Builds knowledge graph nodes and edges from content
│   │   ├── matching_service.py                        # Matches students into compatible study groups via AI
│   │   ├── quiz_context_service.py                    # Manages per-session quiz state and context window
│   │   ├── social_cache_service.py                    # Caches room membership and presence for social features
│   │   └── storage_service.py                         # Avatar and asset uploads via Supabase Storage
│   │
│   └── tests/
│       ├── conftest.py                                # Shared pytest fixtures (mock Supabase, Gemini, etc.)
│       ├── fixtures/                                  # Test fixture data (sample PDFs, JSON payloads)
│       ├── README.md                                  # Notes on running and writing backend tests
│       ├── test_achievement_service.py                # Tests for achievement checking and granting
│       ├── test_admin_routes.py                       # Tests for admin role, achievement, and cosmetic endpoints
│       ├── test_assignment_dedupe.py                  # Tests for assignment deduplication logic
│       ├── test_calendar_routes.py                    # Tests for calendar sync endpoints
│       ├── test_config.py                             # Tests that config loads env vars correctly
│       ├── test_docling_integration.py                # Integration tests for the Docling OCR backend
│       ├── test_documents_routes.py                   # Tests for document upload and processing endpoints
│       ├── test_encryption.py                         # Tests for AES-256-GCM helpers and the *_if_present fallbacks
│       ├── test_extraction_backends.py                # Tests for OCR backend selection and fallback chain
│       ├── test_extraction_service.py                 # Tests for the OCR extraction router
│       ├── test_flashcard_import_routes.py            # Tests for the flashcard import endpoint
│       ├── test_flashcard_import_service.py           # Tests for parsing/extracting flashcards from each input type
│       ├── test_gemini_service.py                     # Tests for Gemini API wrapper behavior
│       ├── test_gradebook_routes.py                   # Tests for gradebook endpoints
│       ├── test_gradebook_service.py                  # Tests for grade calculation logic
│       ├── test_graph_service.py                      # Tests for knowledge graph construction
│       ├── test_learn_routes.py                       # Tests for the streaming tutoring chat endpoint
│       ├── test_ocr_pipeline.py                       # Tests for end-to-end OCR pipeline
│       ├── test_onboarding_routes.py                  # Tests for onboarding endpoint validation
│       ├── test_profile_routes.py                     # Tests for profile, settings, and cosmetics endpoints
│       ├── test_quiz_routes.py                        # Tests for quiz session endpoints
│       ├── test_shared_course_context.py              # Tests for shared course context injection
│       ├── test_social_messages.py                    # Tests for room chat message endpoints
│       ├── test_storage_service.py                    # Tests for avatar upload via Supabase Storage
│       ├── test_study_guide_routes.py                 # Tests for study guide generation endpoints
│       └── test_supabase.py                           # Integration tests against Supabase connection
│
└── frontend/
    ├── next.config.ts                                 # Next.js build and runtime configuration
    ├── tsconfig.json                                  # TypeScript compiler options
    ├── package.json                                   # Node dependencies and npm scripts
    ├── package-lock.json                              # Locked dependency tree
    ├── eslint.config.mjs                              # ESLint rules for the frontend
    ├── postcss.config.mjs                             # PostCSS config (Tailwind plugin)
    ├── wrangler.toml                                  # Cloudflare Workers config (used by @opennextjs/cloudflare)
    ├── Dockerfile                                     # Frontend container image definition
    ├── .dockerignore                                  # Files excluded from the Docker build context
    ├── .env.local                                     # Local frontend secrets (not committed)
    ├── README.md                                      # Frontend-specific setup notes
    │
    ├── public/
    │   ├── sapling-icon.svg                           # App icon used in favicon and UI
    │   └── sapling-word-icon.png                      # Full wordmark logo for navbar/branding
    │
    └── src/
        ├── middleware.ts                              # Next.js middleware for auth guards on protected routes
        │
        ├── app/
        │   ├── layout.tsx                             # Root layout: UserContext, providers, global styles
        │   ├── page.tsx                               # Landing page (sign-in is a modal launched from here)
        │   ├── error.tsx                              # Global Next.js error boundary page
        │   ├── globals.css                            # Tailwind base styles and CSS custom properties
        │   ├── about/page.tsx                         # About page
        │   ├── api/auth/session/route.ts              # Next.js API route for session token exchange
        │   ├── auth/callback/page.tsx                 # OAuth popup callback that posts the code back to opener
        │   ├── careers/                               # Careers listing + per-job detail pages with apply form
        │   ├── flashcards/page.tsx                    # Public flashcard study (entered from the shell)
        │   ├── onboarding/page.tsx                    # Onboarding entry (renders OnboardingFlow)
        │   ├── pending/page.tsx                       # Holding page for unapproved users awaiting access
        │   ├── privacy/page.tsx                       # Privacy policy page
        │   ├── terms/page.tsx                         # Terms of service page
        │   │
        │   └── (shell)/                               # Route group: every page inside renders inside ShellFrame (SideNav + TopNav)
        │       ├── layout.tsx                         # Shell layout that wraps children with SideNav and content frame
        │       ├── achievements/page.tsx              # Achievements gallery page
        │       ├── admin/page.tsx                     # Admin panel (role/cosmetic/user management)
        │       ├── calendar/page.tsx                  # Assignment calendar timeline
        │       ├── course-planner/page.tsx            # Course planner tool entry
        │       ├── dashboard/page.tsx                 # User dashboard
        │       ├── gradebook/page.tsx                 # Gradebook landing (per-course summaries)
        │       ├── gradebook/[courseId]/page.tsx      # Per-course gradebook detail
        │       ├── learn/page.tsx                     # AI tutoring session entry
        │       ├── library/page.tsx                   # Document library
        │       ├── profile/[userId]/page.tsx          # Public user profile by id
        │       ├── settings/page.tsx                  # User settings (profile editing, cosmetics, sign out)
        │       ├── social/page.tsx                    # Study rooms and peer matching
        │       ├── study/page.tsx                     # Study session shell (rendered with FlashcardsPanel)
        │       └── tree/page.tsx                      # Knowledge graph tree visualization
        │
        ├── components/
        │   ├── AchievementUnlockToast.tsx             # Toast shown when an achievement unlocks
        │   ├── AchievementUnlockWatcher.tsx           # Polls for newly unlocked achievements and fires toasts
        │   ├── AIDisclaimerChip.tsx                   # Small chip shown on AI-generated content
        │   ├── AtmosphericBackdrop.tsx                # Animated ambient background used on landing/auth surfaces
        │   ├── Avatar.tsx                             # User avatar with initials fallback
        │   ├── AvatarFrame.tsx                        # Decorative frame around avatar from equipped cosmetics
        │   ├── ChatPanel.tsx                          # Chat shell with input + AI disclaimer (renders MarkdownChat inside)
        │   ├── CustomSelect.tsx                       # Styled dropdown select component
        │   ├── Dialog.tsx                             # Reusable modal/dialog primitive
        │   ├── DisclaimerModal.tsx                    # First-use AI disclaimer modal
        │   ├── DocumentUploadModal.tsx                # Drag-and-drop upload modal for course documents
        │   ├── ErrorBoundary.tsx                      # React error boundary wrapper
        │   ├── FeedbackFlow.tsx                       # Multi-step general feedback submission flow
        │   ├── FloatingActions.tsx                    # Floating action buttons (feedback, report, etc.)
        │   ├── FunctionPlot.tsx                       # function-plot.js renderer used by MarkdownChat
        │   ├── HowItWorks.tsx                         # Landing page section explaining the product
        │   ├── Icon.tsx                               # Centralized SVG icon component
        │   ├── KnowledgeGraph.tsx                     # D3-powered interactive knowledge graph
        │   ├── ManageCoursesModal.tsx                 # Modal for adding/removing courses
        │   ├── MarkdownChat.tsx                       # Markdown renderer with math (KaTeX), mermaid, plots, theorem callouts
        │   ├── MermaidBlock.tsx                       # mermaid diagram renderer used by MarkdownChat
        │   ├── MiniStat.tsx                           # Compact stat tile component
        │   ├── NameColorRenderer.tsx                  # Renders a username with equipped name-color cosmetic
        │   ├── OnboardingFlow.tsx                     # Multi-step onboarding flow (school, major, year, courses)
        │   ├── Pill.tsx                               # Small rounded pill/tag component
        │   ├── ProfileView.tsx                        # Public profile renderer (used by /profile/[userId])
        │   ├── QuizPanel.tsx                          # Quiz UI for answering and reviewing questions
        │   ├── ReportIssueFlow.tsx                    # Flow for users to report bugs or content issues
        │   ├── RoleBadge.tsx                          # Badge displaying a user's role
        │   ├── SessionFeedbackFlow.tsx                # In-session feedback prompt
        │   ├── SessionFeedbackGlobal.tsx              # Global wrapper that triggers session feedback
        │   ├── SessionSummary.tsx                     # Post-session summary
        │   ├── SharedContextToggle.tsx                # Toggle to enable/disable shared course context in chat
        │   ├── ShellFrame.tsx                         # Layout frame used by the (shell) route group (SideNav + content)
        │   ├── SideNav.tsx                            # Collapsible left rail with main navigation
        │   ├── SignInModal.tsx                        # Sign-in modal launched from landing (Google OAuth popup flow)
        │   ├── Skeleton.tsx                           # Loading skeleton variants used across screens
        │   ├── Sparkline.tsx                          # Tiny inline sparkline chart
        │   ├── TitleFlair.tsx                         # Decorative flair rendered next to user titles
        │   ├── ToastProvider.tsx                      # Global toast notification context and renderer
        │   ├── TopBar.tsx                             # Header bar within the shell (breadcrumb, actions)
        │   ├── TopNav.tsx                             # Top navigation bar for non-shell (public) pages
        │   │
        │   ├── flashcards/
        │   │   ├── FlashcardImportModal.tsx           # Tabbed modal for importing flashcards
        │   │   ├── ParsedCardsTable.tsx               # Editable table of parsed cards before saving
        │   │   └── tabs/                              # Per-source tabs: AiTab, PasteTab, PhotoTab, UploadTab, UrlTab
        │   │
        │   ├── Gradebook/
        │   │   ├── AssignmentList.tsx                 # List of assignments with grades
        │   │   ├── AssignmentModal.tsx                # Edit/create assignment modal
        │   │   ├── CategoryPanel.tsx                  # Per-category breakdown panel
        │   │   ├── EditWeightsModal.tsx               # Modal to edit category weights
        │   │   ├── LetterScaleEditor.tsx              # Modal to edit per-course letter-grade thresholds
        │   │   ├── SemesterChips.tsx                  # Semester filter chips
        │   │   └── SyllabusUploadFlow.tsx             # Upload syllabus → preview categories → apply
        │   │
        │   └── screens/                               # Screen-level renderers used by (shell) page.tsx files
        │       ├── Achievements.tsx
        │       ├── Admin.tsx
        │       ├── Calendar.tsx
        │       ├── Dashboard.tsx
        │       ├── Gradebook/Course.tsx               # Per-course gradebook detail screen
        │       ├── Gradebook/Landing.tsx              # Gradebook landing screen
        │       ├── Learn.tsx
        │       ├── Library.tsx
        │       ├── Onboarding.tsx
        │       ├── Settings.tsx
        │       ├── Social.tsx
        │       ├── Study.tsx
        │       └── Tree.tsx
        │
        ├── context/
        │   └── UserContext.tsx                        # React context providing authenticated user state globally
        │
        └── lib/
            ├── api.ts                                 # Typed fetch helpers for every backend API endpoint
            ├── avatarUtils.ts                         # Avatar initials/colors helpers
            ├── data.ts                                # Static reference data (constants, enums)
            ├── flashcardParsers.ts                    # Client-side parsers for paste/file flashcard input
            ├── graphUtils.ts                          # Helpers for transforming graph data for D3
            ├── localData.ts                           # Local-storage-backed offline cache for the demo mode
            ├── sessionToken.ts                        # HMAC session token creation and verification
            ├── supabase.ts                            # Supabase browser client singleton
            ├── types.ts                               # Shared TypeScript types
            ├── useAchievementUnlockWatcher.ts         # Hook that polls for unlocked achievements
            ├── useBodyScrollLock.ts                   # Lock body scroll while a modal is open
            ├── useConfirm.ts                          # Imperative confirm-dialog hook
            ├── useIsMobile.ts                         # Viewport size hook
            └── useLayoutPref.ts                       # Persists layout preferences (e.g. sidenav collapsed)
```

## Running Locally

**Backend**
```bash
cd backend
source venv/bin/activate   # fish: source venv/bin/activate.fish
python main.py             # → http://localhost:5000
```

**Frontend**
```bash
cd frontend
npm run dev                # → http://localhost:3000
```

Env files required: `backend/.env` (copy from `backend/.env.example`) and `frontend/.env.local` (see README for required vars).

## Tests

Always run tests after any significant edit and fix failures before moving on.

**Backend**
```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -q
```

**Frontend** — no automated test suite on this branch. Jest, its config, and the
previous `src/__tests__/*` files were removed during the revamp. Until a new
harness (Jest or Vitest) is reintroduced, verify frontend changes with:

```bash
cd frontend
npx tsc --noEmit    # type safety
npm run dev         # manual smoke test in the browser
```

Keep tests in sync with the code they cover:
- If you rename or remove a function, update any test that imports it
- If you change how a feature works (not just its interface), update the tests that cover it
- New routes or components don't require tests immediately, but existing tests must stay green

## Architecture Notes

- **Auth & sessions**: Google OAuth runs as a popup launched from `SignInModal` on the landing page (no `/signin` page). The popup hits `routes/auth.py`, which issues HMAC session tokens, and `auth/callback/page.tsx` posts the code back to the opener window. The callback then fetches `/api/auth/me` to hydrate name + avatar (PII is encrypted at rest, see below). The frontend stores tokens via `lib/sessionToken.ts`. `middleware.ts` guards protected routes (`/dashboard`, `/learn`, `/study`, `/tree`, `/library`, `/calendar`, `/social`, `/settings`, `/achievements`, `/admin`, `/gradebook`, `/course-planner`) by verifying the token before rendering. `services/auth_guard.py` provides `require_self` and `require_admin` dependencies for backend route protection.
- **Column-level encryption**: Sensitive Supabase columns are encrypted at rest with AES-256-GCM (`services/encryption.py`). The key is loaded from `ENCRYPTION_KEY` (32 bytes as 64 hex chars; generate via `python -c "import secrets; print(secrets.token_hex(32))"`). Routes encrypt at write boundaries and decrypt at read boundaries — never store or log plaintext after a write or before a decrypt.
  - **Encrypted today**: user PII (`users.name`/`first_name`/`last_name`/`bio`/`location`), Google OAuth tokens, document `summary` + `concept_notes`, `messages.content`, `room_messages.text`, `sessions.summary_json`, gradebook assignment `notes` + `points`, calendar assignment `notes`.
  - **Use `decrypt_if_present` / `decrypt_numeric`** when reading — they fall back to the raw value if decryption fails (so partially-backfilled tables don't break). Use `encrypt_if_present` / `encrypt_json` when writing.
  - **Adding a new encrypted column**: 1) update `migration_encryption_text_columns.sql` (or add a new migration) to retype the column to TEXT — ciphertext is base64; 2) wire `encrypt_if_present` into every write path; 3) wire `decrypt_if_present` into every read path including AI prompt builders (`learn.py`, `quiz.py`, `study_guide.py`, `flashcards.py`); 4) run `backend/db/backfill_encryption.py` to encrypt existing plaintext rows.
  - **AI prompts must decrypt first** — student names, document summaries, and concept notes are all decrypted before being injected into Gemini prompts.
- **Shell layout**: All authenticated pages live under `app/(shell)/` and share the `ShellFrame` layout (collapsible `SideNav` + content). Public marketing pages (`/`, `/about`, `/careers`, `/privacy`, `/terms`) sit at the top level and use `TopNav`.
- **Gemini model selection**: Routed per use case in `services/gemini_service.py`, which exposes `MODEL_DEFAULT = "gemini-2.5-flash"` and `MODEL_LITE = "gemini-2.5-flash-lite"`. `call_gemini`, `call_gemini_json`, and `call_gemini_multiturn` all accept a `model` kwarg.
  - **Flash (default)** — tutoring chat (`routes/learn.py`), `_process_document` (because it generates math/markdown concept notes), study guide, course context, social matching.
  - **Flash-lite** — quiz generation + post-answer context update (`routes/quiz.py`), concept suggestions (`routes/documents.py`).
  - When adding a new Gemini call, default to `MODEL_DEFAULT` and only drop to `MODEL_LITE` for short structured tasks where weaker reasoning won't hurt quality.
- **User approval gate**: New users are created with `is_approved = false`. Unapproved users are redirected to `/pending` by the middleware. Admins approve users via the admin panel (`/admin`).
- **Onboarding**: After first sign-in, users go through `OnboardingFlow.tsx` (school, major, year, courses), which writes to the backend via `routes/onboarding.py`.
- **Profiles & settings**: `routes/profile.py` handles public profiles, user settings, cosmetic equipping, featured achievements, and account deletion. The frontend has separate `/profile/[userId]` (public view) and `/settings` (editing + sign out) pages.
- **Roles & achievements**: Roles and achievements are managed via `routes/admin.py`. Achievements are auto-granted by `services/achievement_service.py` when event thresholds are met. Cosmetics (avatar frames, name colors, title flairs) can be equipped and shown on profiles.
- **Document AI**: `routes/documents.py` does classification, summarization, syllabus assignment + grading-category extraction, and concept-note generation in a single Gemini call (`_process_document`). Concept notes are markdown and may include `$math$`, ```` ```mermaid ```` blocks, ```` ```plot ```` blocks, and `:::theorem`/`:::definition`/etc. directives — `MarkdownChat.tsx` renders all of these.
- **Gradebook**: `routes/gradebook.py` + `services/gradebook_service.py` own categories (with weights), assignments, per-course letter-scale overrides, current grade, and category grade. Syllabus uploads flow through `SyllabusUploadFlow.tsx`, which previews extracted categories before applying them (replacing existing categories and deduping assignments via `assignment_dedupe.py`).
- **Flashcard import**: `services/flashcard_import_service.py` parses flashcards from paste, file upload, URL, AI prompt, or photo. The frontend modal `FlashcardImportModal.tsx` has one tab per source.
- **Chat realtime**: Room chat subscribes to Supabase Realtime directly from the frontend using `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Messages are written via the backend API, which uses `SUPABASE_SERVICE_KEY`.
- **Session feedback**: triggered in `learn/page.tsx` — fires after every 3 session ends (no cooldown) and on navigate-away with a 2-day cooldown.
- **OCR routing**: `services/extraction_service.py` is a thin router in front of `services/extraction_backends/`. Engine selection is driven by the `OCR_ENGINE` env var: `docling` (default, layout-aware markdown), `auto` (Docling plus GOT-OCR 2.0 fallback for pages Docling flags as low char-density or math-without-LaTeX — only active when `GOT_OCR_ENABLED=true`), or `tesseract` (legacy). All heavy ML backends are lazy-imported so cold start stays well under a second. Docling/GOT-OCR failures degrade gracefully to Tesseract, then raise `RuntimeError` so `routes/extract.py` can surface the existing 503.
- **Cloudflare deploy**: The frontend deploys to Cloudflare Workers via `@opennextjs/cloudflare`. `wrangler.toml` is the Worker config (Pages is incompatible with the OpenNext adapter).

## Code Style

- Keep changes minimal and focused — don't refactor surrounding code unless asked
- No docstrings or comments unless the logic is non-obvious
- No backwards-compatibility shims for removed code — delete it cleanly
