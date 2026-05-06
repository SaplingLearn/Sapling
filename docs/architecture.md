# Sapling Backend Architecture

The backend ingests student documents, runs Gemini-powered classification, summarization, and assignment/concept extraction, and serves a knowledge-graph-backed tutor and quiz engine to the React frontend.

## High-level shape

A single FastAPI app (`backend/main.py:24`) mounts every router under `/api/<name>`. Supabase is both the datastore and the source of user identity — accessed exclusively through a thin PostgREST wrapper (`backend/db/connection.py:71`) using a service-role key. Gemini is the only LLM provider today and is called via four functions in `services/gemini_service.py`. The React app in `frontend/` is the only consumer of these endpoints; there is no public/third-party API surface.

## Request paths

- **Document upload** — `backend/routes/documents.py:266` `upload_document` runs sequentially: validate → `extraction_service.extract_text_from_file` → `_process_document` (one `call_gemini_json` for category/summary/concepts/assignments) → optional `save_assignments_to_db` (`backend/services/calendar_service.py:62`) for syllabi → optional `apply_graph_update` for syllabus/assignment concepts → insert `documents` row → invalidate `study_guides` cache → `check_achievements("documents_uploaded")`.
- **Chat with tutor** — `backend/routes/learn.py:311` `chat` rebuilds the system prompt via `build_system_prompt` (`backend/routes/learn.py:152`) using the live graph + course documents + cached `course_context`, calls `call_gemini_multiturn`, splits out `<graph_update>` via `extract_graph_update`, persists the assistant message, then calls `apply_graph_update` which lazy-imports `update_course_context` for any touched course.
- **Quiz generation** — `backend/routes/quiz.py:26` `generate_quiz` loads the target node + prior `quiz_context`, fills `prompts/quiz_generation.txt`, and (when `use_shared_context`) appends class-wide misconceptions and weak areas from `course_context_service.get_course_context` via `prompt += ...` before `call_gemini_json`. Result is stored in `quiz_attempts`.
- **Study guide** — `backend/routes/study_guide.py:18` `_generate_and_insert` fetches the exam row + all course `documents`, concatenates `summary` + `concept_notes` into a context block, calls `call_gemini_json`, and inserts into `study_guides`. The `/guide` GET serves cache-first; `upload_document` invalidates by deleting that user+course's rows.
- **Calendar / syllabus** — covered by the syllabus branch of `upload_document` above (`save_assignments_to_db` deduplicates by trimmed-title + calendar-day). The standalone `backend/services/calendar_service.py:77` `process_and_save_syllabus` exists for direct OCR→Gemini→DB use but is not currently wired to a route.

## LLM seam (current)

Every LLM call in the codebase routes through `backend/services/gemini_service.py`, which holds a single module-level `genai.Client` pointed at `gemini-2.5-flash`. The four public entry points are `call_gemini` (`:62`, plain text), `call_gemini_multiturn` (`:88`, native chat history with system instruction), `call_gemini_json` (`:129`, JSON-mode + tolerant `_extract_json` fallback), and `extract_graph_update` (`:141`, parses the `<graph_update>` block out of tutor replies). This is the legacy seam: new LLM-driven work is intended to land as Pydantic AI agents under `backend/agents/`, replacing call sites incrementally (see `docs/decisions/`). That directory does not exist yet and `pydantic-ai` is not in `requirements.txt`.

## Data layer

All Supabase access goes through `backend/db/connection.py:71` `table()`, which returns a `SupabaseTable` wrapping `select/insert/update/upsert/delete` over PostgREST with a single shared `httpx.Client`. There is no ORM and no migration framework — schema lives in `backend/db/supabase_schema.sql` plus hand-numbered `migration_*.sql` files. The client uses `SUPABASE_SERVICE_KEY` (service role), so PostgREST runs without RLS enforcement; ownership is enforced in route code by filtering every query on `user_id` and validating via `_validate_user`.

## Background work

Almost everything currently runs inline on the request path. The one true background task is in `backend/routes/quiz.py:208`, where FastAPI `background_tasks.add_task(_update_context, ...)` defers the post-quiz context regeneration. `backend/services/course_context_service.py:109` `update_course_context` is called inline from `apply_graph_update` and from course add/delete, but its expensive Gemini summary is hash-gated at `backend/services/course_context_service.py:307` — it only re-runs `_generate_summary_with_gemini` when the stats hash changes. Achievement checks (`check_achievements`) are also inline and wrapped in best-effort `try/except`.

## Known sharp edges

- `upload_document` is fully sequential: text extraction, the classify/summarize/extract LLM call, optional assignment save, optional graph update, the documents insert, study-guide cache invalidation, and achievement check all run in series on the request thread. Wall-clock ≈ extraction time + LLM time.
- `apply_graph_update` (`backend/services/graph_service.py:375`) is called from two routers with different shapes: `backend/routes/documents.py` passes `{"new_nodes": [...]}` only, while `backend/routes/learn.py` passes the full `{new_nodes, updated_nodes, new_edges, recommended_next}` parsed out of the tutor's `<graph_update>` tag. Quiz scoring does NOT go through it — `backend/routes/quiz.py:161` writes `graph_nodes` directly.
- Quiz prompts manually concatenate course-wide misconceptions onto the prompt string (`backend/routes/quiz.py:82`, `prompt += "\n\n" + ...`) after the template substitution, so the prompt template alone does not reflect the final prompt sent to Gemini.
- `apply_graph_update` lazy-imports `services.course_context_service` to avoid a circular import; that import path also swallows exceptions so a failing aggregation will not surface to the caller.
- `course_context_service.update_course_context` writes to `course_concept_stats` and `course_summary` synchronously inside the request — a chat turn that touches several courses incurs that aggregation cost serially before returning.
- Document-upload concept population only runs for `category in ("syllabus", "assignment")`; lecture notes, slides, readings, and study guides do NOT auto-populate the graph from upload — that path is the separate `/scan-concepts` endpoints (`backend/routes/documents.py:408`, `:438`).
- Sessions are lazy: `start_session` does not persist anything; the row is materialized inside `_consume_pending` on the first `/chat` call, so a session that's started and abandoned leaves no DB trace.
