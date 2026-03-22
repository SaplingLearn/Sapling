# Sapling — Claude Code Guidelines

## Project Overview

Sapling is an AI-powered study companion. It has two services:

- **Frontend** — Next.js (TypeScript), lives in `frontend/`
- **Backend** — FastAPI (Python), lives in `backend/`

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

- **Chat realtime**: `RoomChat.tsx` subscribes to Supabase Realtime directly from the frontend using `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Messages are written via the backend API, which uses `SUPABASE_SERVICE_KEY`.
- **Document AI**: `routes/documents.py` does classification, summarization, and syllabus assignment extraction in a single Gemini call (`_process_document`). Assignments come back in the AI response, not from a separate function call.
- **Session feedback**: triggered in `learn/page.tsx` — fires after every 3 session ends (no cooldown) and on navigate-away with a 2-day cooldown.
- **ESM packages in tests**: `remark-math` and `rehype-katex` are ESM-only. They are mocked in `src/__mocks__/` so Jest can handle them. If you add new ESM-only packages that break tests, add a mock there and map it in `jest.config.js`.

## Code Style

- Keep changes minimal and focused — don't refactor surrounding code unless asked
- No docstrings or comments unless the logic is non-obvious
- No backwards-compatibility shims for removed code — delete it cleanly
