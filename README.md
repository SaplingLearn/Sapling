# Sapling

An AI-powered study companion that builds a live knowledge graph as you learn.

!["preview"](landingpage.png "Preview")
![Python](https://img.shields.io/badge/-Python-3776AB?style=flat-square&logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=fff)
![Next.js](https://img.shields.io/badge/Next.js-000000?logo=nextdotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=fff)
![Google Gemini](https://img.shields.io/badge/Gemini-8E75B2?logo=google&logoColor=white)
![D3.js](https://img.shields.io/badge/D3.js-F9A03C?logo=d3dotjs&logoColor=white)
![Git](https://img.shields.io/badge/-Git-F05032?style=flat-square&logo=git&logoColor=white)

## Overview

Sapling is a study tool that adapts to how you learn. Chat with an AI tutor across three teaching modes, take adaptive quizzes, track assignments from your syllabus, and compare progress with classmates in study rooms. As you learn, a live knowledge graph maps your mastery in real time.

## Features

* **Live Knowledge Graph** — Your understanding is visualized as a growing node graph. Mastery scores update dynamically after every session and quiz.
* **Three Teaching Modes** — Socratic (guided reasoning), Expository (direct explanation), and TeachBack (you explain, Sapling corrects).
* **Adaptive Quizzes** — AI-generated quizzes targeting your weakest concepts, with difficulty scaling based on your performance.
* **Flashcards** — Generate AI flashcards per course, study by topic with spaced-repetition ratings (Easy / Hard / Forgot), and track review history.
* **Study Guide** — Generate a Gemini-powered exam study guide from your uploaded course materials. Guides are cached per exam and can be regenerated at any time.
* **Class Intelligence** — Aggregates anonymized class-wide patterns to surface common misconceptions and weak areas, personalizing your sessions.
* **Calendar & Syllabus Tracking** — Paste your syllabus and Sapling extracts assignments, deadlines, and topics automatically.
* **Document Library** — Upload PDFs and notes; Sapling extracts summaries, key takeaways, and flashcard topics to enrich your knowledge graph and study guides.
* **Study Rooms** — Invite classmates, compare knowledge graphs, and track relative mastery across your group.
* **Room Chat** — Real-time text chat with avatars inside each study room.
* **User Profiles** — Public profiles with academic info, bio, featured achievements, and equipped cosmetics.
* **Achievements & Cosmetics** — Unlock achievements by hitting milestones (sessions, quizzes, streaks). Equip cosmetic rewards like avatar frames, name colors, and title flairs.
* **Roles & Admin Panel** — Role-based access control with an admin panel for user approval, role assignment, and content management.
* **Onboarding Flow** — Multi-step onboarding that collects school, major, year, and courses after first sign-in.
* **Feedback & Issue Reporting** — Submit session feedback or report bugs directly from the app via the Navbar.

## Tech Stack

* **Frontend** — Next.js (TypeScript) with D3.js for interactive graph visualization
* **Backend** — FastAPI (Python) serving a REST API with structured Gemini prompts
* **AI** — Google Gemini for tutoring, quiz generation, graph updates, and syllabus extraction
* **OCR** — Docling (layout-aware PDF → Markdown) with GOT-OCR 2.0 fallback for math/handwriting; Tesseract retained as a legacy fallback
* **Database** — Supabase (PostgreSQL) for all persistent data

## Usage

**Backend**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # fish: source venv/bin/activate.fish
pip install -r requirements.txt
cp .env.example .env       # fill in GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
python3 main.py            # → http://localhost:5000
```

**Frontend**
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:5000" > .env.local
npm run dev                # → http://localhost:3000
```

## API Endpoints

**Learn**
- `POST` `/api/learn/start-session` — Start a tutoring session
- `POST` `/api/learn/chat` — Send a chat message
- `POST` `/api/learn/action` — Send a structured action (e.g. quiz, recap)
- `POST` `/api/learn/end-session` — End a session
- `GET`  `/api/learn/sessions/{user_id}` — List past sessions

**Graph**
- `GET`  `/api/graph/{user_id}` — Fetch the user's knowledge graph
- `GET`  `/api/graph/{user_id}/recommendations` — Get next-concept recommendations
- `GET`  `/api/graph/{user_id}/courses` — List courses

**Quiz**
- `POST` `/api/quiz/generate` — Generate an adaptive quiz
- `POST` `/api/quiz/submit` — Submit answers and update mastery

**Flashcards**
- `POST` `/api/flashcards/generate` — Generate flashcards for a topic
- `GET`  `/api/flashcards/user/{user_id}` — Fetch a user's flashcards
- `POST` `/api/flashcards/rate` — Rate a card (Easy / Hard / Forgot)
- `DELETE` `/api/flashcards/{card_id}` — Delete a card

**Study Guide**
- `GET`  `/api/study-guide/{user_id}/guide` — Get (or generate) a study guide for an exam
- `GET`  `/api/study-guide/{user_id}/cached` — List all cached study guides
- `GET`  `/api/study-guide/{user_id}/courses` — List courses for guide generation
- `GET`  `/api/study-guide/{user_id}/exams` — List exam-type assignments
- `POST` `/api/study-guide/regenerate` — Invalidate cache and regenerate a guide

**Calendar**
- `POST` `/api/calendar/extract` — Extract assignments from a syllabus
- `GET`  `/api/calendar/upcoming/{user_id}` — Fetch upcoming assignments
- `POST` `/api/calendar/save` — Save extracted assignments

**Documents**
- `POST` `/api/documents/upload` — Upload and process a document
- `GET`  `/api/documents/user/{user_id}` — List a user's documents
- `DELETE` `/api/documents/doc/{doc_id}` — Delete a document

**Social**
- `POST` `/api/social/rooms/create` — Create a study room
- `POST` `/api/social/rooms/join` — Join a study room by invite code
- `GET`  `/api/social/rooms/{user_id}` — List a user's rooms
- `GET`  `/api/social/rooms/{room_id}/overview` — Room overview with AI-generated group summary
- `GET`  `/api/social/rooms/{room_id}/activity` — Recent activity feed for a room
- `POST` `/api/social/rooms/{room_id}/match` — Find study partners within a room
- `POST` `/api/social/rooms/{room_id}/leave` — Leave a room
- `DELETE` `/api/social/rooms/{room_id}/members/{member_id}` — Kick a member (room leader only)
- `GET`  `/api/social/rooms/{room_id}/messages` — Fetch room chat messages
- `POST` `/api/social/rooms/{room_id}/messages` — Send a chat message
- `POST` `/api/social/school-match` — Find study partners school-wide
- `GET`  `/api/social/students` — List all students with mastery stats

**Auth**
- `GET`  `/api/auth/google` — Redirect to Google OAuth consent screen
- `GET`  `/api/auth/google/callback` — OAuth callback, issues session token
- `GET`  `/api/auth/me` — Get current user from session token

**Onboarding**
- `GET`  `/api/onboarding/courses` — Search courses by name or code
- `POST` `/api/onboarding/profile` — Save onboarding profile data

**Profile**
- `GET`  `/api/profile/{user_id}` — Public profile with roles, achievements, cosmetics
- `PUT`  `/api/profile/{user_id}` — Update profile fields (bio, major, links, etc.)
- `PUT`  `/api/profile/{user_id}/settings` — Update user settings
- `POST` `/api/profile/{user_id}/avatar` — Upload a profile avatar
- `POST` `/api/profile/{user_id}/equip` — Equip or unequip a cosmetic item
- `PUT`  `/api/profile/{user_id}/featured-role` — Set featured role on profile
- `PUT`  `/api/profile/{user_id}/featured-achievements` — Set featured achievements
- `DELETE` `/api/profile/{user_id}` — Delete account

**Admin**
- `POST` `/api/admin/roles` — Create a role
- `POST` `/api/admin/roles/assign` — Assign a role to a user
- `POST` `/api/admin/roles/revoke` — Revoke a role from a user
- `POST` `/api/admin/achievements` — Create an achievement
- `POST` `/api/admin/achievements/triggers` — Create an achievement trigger
- `POST` `/api/admin/achievements/grant` — Manually grant an achievement
- `POST` `/api/admin/cosmetics` — Create a cosmetic item
- `POST` `/api/admin/approve/{user_id}` — Approve a pending user

**Feedback**
- `POST` `/api/feedback/feedback` — Submit session or general feedback
- `POST` `/api/feedback/issue-reports` — Submit a bug/issue report

## Environment Variables

**`backend/.env`**

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Google Gemini API key |
| `SUPABASE_URL` | ✅ | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | ✅ | Supabase service role key |
| `PORT` | — | Backend port (default `5000`) |
| `FRONTEND_URL` | — | Allowed CORS origin (default `http://localhost:3000`) |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (for sign-in and Calendar) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `SESSION_SECRET` | — | HMAC secret for session tokens (min 32 bytes) |

**`frontend/.env.local`**

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | ✅ | Backend base URL (e.g. `http://localhost:5000`) |
| `SESSION_SECRET` | — | Same HMAC secret as backend (for middleware token verification) |

## License

Copyright (c) 2026 Andres Lopez, Jack He, Luke Cooper, and Jose Gael Cruz-Lopez
