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
│   │   ├── dedup_nodes.py                             # One-off script to deduplicate knowledge graph nodes
│   │   └── archive/
│   │       ├── init_db.py                             # Old DB init script (archived, no longer used)
│   │       ├── schema.sql                             # Old schema before Supabase migration
│   │       └── seed.py                                # Old Python-based seed script
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
│   │   ├── syllabus_extraction.txt                    # Prompt for extracting assignments from a syllabus
│   │   └── shared_context.txt                         # Prompt fragment injected when shared course context is on
│   │
│   ├── routes/
│   │   ├── admin.py                                   # Admin endpoints for role, achievement, cosmetic, and user management
│   │   ├── auth.py                                    # Google OAuth sign-in, session tokens, and user upsert
│   │   ├── calendar.py                                # Endpoints to read and sync assignment calendar events
│   │   ├── careers.py                                 # Endpoints for job listings and application submission
│   │   ├── documents.py                               # Upload, classify, summarize, and extract from docs
│   │   ├── extract.py                                 # OCR and text extraction pipeline for uploaded files
│   │   ├── feedback.py                                # Endpoints to submit session and general user feedback
│   │   ├── flashcards.py                              # CRUD endpoints for user flashcard decks
│   │   ├── graph.py                                   # Endpoints to build and query the knowledge graph
│   │   ├── learn.py                                   # Streaming AI tutoring chat endpoint (SSE)
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
│   │   ├── extraction_service.py                      # Orchestrates OCR → text extraction for uploaded files
│   │   ├── gemini_service.py                          # Wrapper around the Gemini API (chat, streaming, vision)
│   │   ├── graph_service.py                           # Builds knowledge graph nodes and edges from content
│   │   ├── matching_service.py                        # Matches students into compatible study groups via AI
│   │   ├── quiz_context_service.py                    # Manages per-session quiz state and context window
│   │   ├── social_cache_service.py                    # Caches room membership and presence for social features
│   │   └── storage_service.py                         # Avatar and asset uploads via Supabase Storage
│   │
│   └── tests/
│       ├── conftest.py                                # Shared pytest fixtures (mock Supabase, Gemini, etc.)
│       ├── README.md                                  # Notes on running and writing backend tests
│       ├── test_achievement_service.py                # Tests for achievement checking and granting
│       ├── test_admin_routes.py                       # Tests for admin role, achievement, and cosmetic endpoints
│       ├── test_assignment_dedupe.py                  # Tests for assignment deduplication logic
│       ├── test_calendar_routes.py                    # Tests for calendar sync endpoints
│       ├── test_config.py                             # Tests that config loads env vars correctly
│       ├── test_documents_routes.py                   # Tests for document upload and processing endpoints
│       ├── test_extraction_service.py                 # Tests for the OCR extraction pipeline
│       ├── test_gemini_service.py                     # Tests for Gemini API wrapper behavior
│       ├── test_graph_service.py                      # Tests for knowledge graph construction
│       ├── test_learn_routes.py                       # Tests for the streaming tutoring chat endpoint
│       ├── test_ocr_pipeline.py                       # Tests for end-to-end OCR pipeline
│       ├── test_onboarding_routes.py                  # Tests for onboarding endpoint validation
│       ├── test_profile_routes.py                     # Tests for profile, settings, and cosmetics endpoints
│       ├── test_quiz_routes.py                        # Tests for quiz session endpoints
│       ├── test_shared_course_context.py              # Tests for shared course context injection
│       ├── test_storage_service.py                    # Tests for avatar upload via Supabase Storage
│       └── test_supabase.py                           # Integration tests against Supabase connection
│
└── frontend/
    ├── next.config.ts                                 # Next.js build and runtime configuration
    ├── tsconfig.json                                  # TypeScript compiler options
    ├── tsconfig.tsbuildinfo                           # TypeScript incremental build cache
    ├── package.json                                   # Node dependencies and npm scripts
    ├── package-lock.json                              # Locked dependency tree
    ├── jest.config.js                                 # Jest test runner config (module aliases, transforms)
    ├── jest.setup.js                                  # Jest global setup (testing-library, env vars)
    ├── eslint.config.mjs                              # ESLint rules for the frontend
    ├── postcss.config.mjs                             # PostCSS config (Tailwind plugin)
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
        ├── app/
        │   ├── layout.tsx                             # Root layout: Navbar, UserContext, global providers
        │   ├── page.tsx                               # Landing/home page
        │   ├── error.tsx                              # Global Next.js error boundary page
        │   ├── globals.css                            # Tailwind base styles and CSS custom properties
        │   ├── icon.svg                               # App icon for Next.js metadata
        │   ├── about/page.tsx                         # About page with mission and team info
        │   ├── achievements/page.tsx                  # Achievements gallery and progress page
        │   ├── admin/page.tsx                         # Admin panel for user approval, roles, and cosmetics
        │   ├── api/auth/session/route.ts              # Next.js API route for session token exchange
        │   ├── calendar/page.tsx                      # Assignment calendar view with due-date timeline
        │   ├── dashboard/page.tsx                     # User dashboard showing docs, assignments, progress
        │   ├── flashcards/page.tsx                    # Flashcard study and deck management page
        │   ├── learn/page.tsx                         # AI tutoring session page (mode select + chat)
        │   ├── library/page.tsx                       # Document library for uploaded course materials
        │   ├── pending/page.tsx                       # Holding page for unapproved users awaiting access
        │   ├── privacy/page.tsx                       # Privacy policy page
        │   ├── profile/page.tsx                       # Public user profile with achievements and academic info
        │   ├── settings/page.tsx                      # User settings (profile editing, cosmetics, account)
        │   ├── signin/page.tsx                        # Sign-in page with Google OAuth
        │   ├── signin/callback/page.tsx               # OAuth callback handler that exchanges code for session
        │   ├── social/page.tsx                        # Study rooms and peer matching page
        │   ├── terms/page.tsx                         # Terms of service page
        │   ├── tree/page.tsx                          # Knowledge graph tree visualization page
        │   ├── careers/
        │   │   ├── jobs.ts                            # Static list of open job positions
        │   │   ├── page.tsx                           # Careers listing page
        │   │   └── [slug]/
        │   │       ├── page.tsx                       # Individual job detail page
        │   │       └── ApplyForm.tsx                  # Job application form component
        │   └── study/
        │       ├── page.tsx                           # Study session entry point (SSR shell)
        │       ├── StudyClient.tsx                    # Client-side study session orchestrator
        │       └── FlashcardsPanel.tsx                # Inline flashcard panel within a study session
        │
        ├── components/
        │   ├── AchievementCard.tsx                    # Card displaying a single achievement with progress
        │   ├── AchievementShowcase.tsx                # Displays featured achievements on a user profile
        │   ├── AchievementUnlockToast.tsx             # Toast notification when an achievement is unlocked
        │   ├── AIDisclaimerChip.tsx                   # Small chip shown on AI-generated content
        │   ├── AssignmentTable.tsx                    # Table displaying assignments with status and due dates
        │   ├── Avatar.tsx                             # User avatar with initials fallback
        │   ├── AvatarFrame.tsx                        # Decorative frame around avatar from equipped cosmetics
        │   ├── ChatPanel.tsx                          # Main AI chat UI with streaming message rendering
        │   ├── CosmeticsManager.tsx                   # UI for equipping/previewing cosmetic items
        │   ├── CustomSelect.tsx                       # Styled dropdown select component
        │   ├── DisclaimerModal.tsx                    # Modal shown on first use with AI disclaimer
        │   ├── ErrorBoundary.tsx                      # React error boundary wrapper for safe rendering
        │   ├── FeedbackFlow.tsx                       # Multi-step general feedback submission flow
        │   ├── HowItWorks.tsx                         # Landing page section explaining the product
        │   ├── KnowledgeGraph.tsx                     # D3-powered interactive knowledge graph visualization
        │   ├── ModeSelector.tsx                       # Selector for choosing AI tutoring mode (Socratic, etc.)
        │   ├── NameColorRenderer.tsx                  # Renders a username with equipped name-color cosmetic
        │   ├── Navbar.tsx                             # Top navigation bar with auth state and links
        │   ├── OnboardingFlow.tsx                     # Multi-step onboarding flow for new users
        │   ├── ProfileBanner.tsx                      # Banner header for user profile pages
        │   ├── QuizPanel.tsx                          # Quiz UI for answering and reviewing questions
        │   ├── ReportIssueFlow.tsx                    # Flow for users to report bugs or content issues
        │   ├── RoleBadge.tsx                          # Badge displaying a user's role (admin, moderator, etc.)
        │   ├── RoomChat.tsx                           # Real-time chat UI for a study room (Supabase Realtime)
        │   ├── RoomList.tsx                           # List of available and joined study rooms
        │   ├── RoomMembers.tsx                        # Displays current members of a study room
        │   ├── RoomOverview.tsx                       # Overview card for a study room (name, topic, members)
        │   ├── SchoolDirectory.tsx                    # Directory for browsing schools and courses
        │   ├── SessionFeedbackFlow.tsx                # In-session feedback prompt after study sessions
        │   ├── SessionFeedbackGlobal.tsx              # Global wrapper that triggers session feedback on navigate
        │   ├── SessionSummary.tsx                     # Post-session summary of topics covered and performance
        │   ├── SharedContextToggle.tsx                # Toggle to enable/disable shared course context in chat
        │   ├── SpaceBackground.tsx                    # Animated starfield canvas background
        │   ├── StudyMatch.tsx                         # UI for finding and joining study partner matches
        │   ├── TitleFlair.tsx                         # Decorative flair rendered next to user titles
        │   ├── ToastProvider.tsx                      # Global toast notification context and renderer
        │   └── UploadZone.tsx                         # Drag-and-drop file upload zone for course documents
        │
        ├── context/
        │   └── UserContext.tsx                        # React context providing authenticated user state globally
        │
        ├── lib/
        │   ├── api.ts                                 # Typed fetch helpers for every backend API endpoint
        │   ├── avatarUtils.ts                         # Utilities for generating avatar initials and colors
        │   ├── graphUtils.ts                          # Helpers for transforming graph data for D3 rendering
        │   ├── sessionToken.ts                        # HMAC session token creation, verification, and helpers
        │   ├── supabase.ts                            # Supabase browser client singleton
        │   └── types.ts                               # Shared TypeScript types used across the frontend
        │
        ├── __mocks__/
        │   ├── rehypeKatex.js                         # Mock for ESM-only rehype-katex (Jest compat)
        │   ├── remarkMath.js                          # Mock for ESM-only remark-math (Jest compat)
        │   └── styleMock.js                           # Mock for CSS/image imports in Jest
        │
        ├── middleware.ts                               # Next.js middleware for auth guards on protected routes
        │
        └── __tests__/
            ├── README.md                              # Notes on frontend test conventions
            ├── achievementCard.test.tsx                # Tests for AchievementCard rendering
            ├── api.test.ts                            # Tests for API helper functions
            ├── authAndPrefillWiring.test.ts           # Tests for auth flow and form pre-fill logic
            ├── chatPanel.test.tsx                     # Tests for ChatPanel rendering and streaming
            ├── dataFetching.test.tsx                  # Tests for data-fetching hooks and loading states
            ├── graphUtils.test.ts                     # Tests for graph transformation utilities
            ├── hydration.test.tsx                     # Tests for SSR/CSR hydration correctness
            ├── profile.test.tsx                       # Tests for profile page rendering
            ├── roleBadge.test.tsx                     # Tests for RoleBadge component
            ├── sessionSummary.test.tsx                # Tests for SessionSummary rendering
            ├── settings.test.tsx                      # Tests for settings page rendering
            ├── signinCallback.test.tsx                # Tests for OAuth callback handling
            └── userContext.test.tsx                   # Tests for UserContext auth state management
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

**Frontend**
```bash
cd frontend
npm test -- --watchAll=false
```

**Backend**
```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -q
```

Keep tests in sync with the code they cover:
- If you rename or remove a function, update any test that imports it
- If you change how a feature works (not just its interface), update the tests that cover it
- New routes or components don't require tests immediately, but existing tests must stay green

## Architecture Notes

- **Auth & sessions**: Google OAuth flow goes through `routes/auth.py`, which issues HMAC session tokens. The frontend stores tokens via `lib/sessionToken.ts`. `middleware.ts` guards protected routes by verifying the token before rendering. `services/auth_guard.py` provides `require_self` and `require_admin` dependencies for backend route protection.
- **User approval gate**: New users are created with `is_approved = false`. Unapproved users are redirected to `/pending` by the middleware. Admins approve users via the admin panel (`/admin`).
- **Onboarding**: After first sign-in, users go through a multi-step `OnboardingFlow.tsx` (replaced the old `OnboardingModal`). The flow collects school, major, year, and courses, then writes to the backend via `routes/onboarding.py`.
- **Profiles & settings**: `routes/profile.py` handles public profiles, user settings, cosmetic equipping, featured achievements, and account deletion. The frontend has separate `/profile` (public view) and `/settings` (editing) pages.
- **Roles & achievements**: Roles (admin, moderator, etc.) and achievements are managed via `routes/admin.py`. Achievements are auto-granted by `services/achievement_service.py` when event thresholds are met. Cosmetics (avatar frames, name colors, title flairs) can be equipped and shown on profiles.
- **Chat realtime**: `RoomChat.tsx` subscribes to Supabase Realtime directly from the frontend using `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Messages are written via the backend API, which uses `SUPABASE_SERVICE_KEY`.
- **Document AI**: `routes/documents.py` does classification, summarization, and syllabus assignment extraction in a single Gemini call (`_process_document`). Assignments come back in the AI response, not from a separate function call.
- **Session feedback**: triggered in `learn/page.tsx` — fires after every 3 session ends (no cooldown) and on navigate-away with a 2-day cooldown.
- **ESM packages in tests**: `remark-math` and `rehype-katex` are ESM-only. They are mocked in `src/__mocks__/` so Jest can handle them. If you add new ESM-only packages that break tests, add a mock there and map it in `jest.config.js`.

## Code Style

- Keep changes minimal and focused — don't refactor surrounding code unless asked
- No docstrings or comments unless the logic is non-obvious
- No backwards-compatibility shims for removed code — delete it cleanly
