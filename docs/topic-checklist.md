# Topic Checklist

On the knowledge map (`/tree`), select a course, then open **Topic checklist**.
The checklist shows significant topics/subtopics, prerequisite gaps, study
status, evidence sources and upcoming quiz/exam dates. Use the status filter to
find unstudied or weak topics. Check a topic after studying it; a checkmark does
not raise mastery or conceal weak mastery. Unchecking removes that manual review
record without deleting tutoring/quiz history.

## Sources and freshness

Generation uses the selected course's stored description, BU catalog chunks
(keyed by BU course code), the student's own nondeleted documents in the selected
offering, tracked course concepts/prerequisite relationships, and quizzes/exams
due in the next 30 days.
The existing catalog scraper/ingestion pipeline supplies catalog knowledge; no
web scraping or new course catalog ingestion is added to the request path.
A course with no academic evidence gets an explicit empty state, rather than
topics inferred from the course title. Catalog coverage depends on the existing
ingested data; this feature does not claim complete knowledge of every BU course.

Outlines are generated on opening/updating the panel only when the evidence hash
changes, including when assessments enter or leave the date window. A GET never
calls the model. Refresh is bounded to 60 seconds, uses the existing worker token
budget and permits six generations per user per minute per backend process.
Failures preserve the previous outline and checkmarks and expose a retry.
Generation reads up to five catalog chunks, the 30 newest documents and the 50
earliest upcoming assessments. Serialized evidence (including IDs, labels and
JSON escaping) has a 60,000-character budget and a 10,000-character per-source text
limit. The response warns when source text or source coverage is shortened.

Assessment links require source evidence of coverage. Generic exam titles still
appear in the upcoming-assessment list but do not imply that every topic is on
that exam. Due dates and assessment IDs come from stored assignments, never from
model output. Model-supplied evidence IDs and hierarchy references are validated.

Mastery remains cumulative per abstract course. The checklist and checkmarks are
per enrollment. An explicit semester never falls back into another semester;
without one, the API prefers the current enrolled term, then the most recent
offering. The panel displays that term and provides a selector for retaken courses
when the global view is All semesters.

Studied topics with mastery below 45% need review. Any studied topic not reviewed
for seven days also needs review. Topics relevant to an assessment within seven
days, weak topics, and topics with weak/untracked prerequisites receive high
priority. Unstudied topics remain separately identifiable. Manual checkmarks
refresh the review date without manufacturing mastery evidence.

## API for frontend integration

All routes use the existing Sapling session and require the session to belong to
`user_id`, plus a current owned enrollment in the requested course/semester.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/topic-checklist/{user_id}/courses/{course_id}` | Cached outline with live priorities and `needs_refresh` |
| POST | `/api/topic-checklist/{user_id}/courses/{course_id}/refresh` | Generate only when evidence changed |
| PATCH | `/api/topic-checklist/{user_id}/courses/{course_id}/topics/{topic_id}` | Body `{"checked": true}` or `{"checked": false}` |

Every route accepts `?semester=Fall%202026` (term labels or IDs). Unknown terms,
unenrolled courses and topics outside the owned checklist return 404; cross-user
requests return 403. Topics have name-derived IDs, `parent_id`, prerequisite IDs,
status, checkmark, mastery, review reasons, source labels and actual assessment
metadata. The frontend client lives in `frontend/src/lib/topicChecklistApi.ts`;
the plain panel can be replaced by the design team without changing the API.

## Deployment and verification

Apply `20261019005643_topic_checklists.sql` through the existing migration runner
**before** deploying the backend to Railway. The normal staging migration and
production promotion workflows remain the authority; do not apply DDL manually
in the Supabase dashboard. The migration is additive, enables RLS and limits
table access to the backend service role. Outline content is encrypted using the
existing `ENCRYPTION_KEY`; deleting an enrollment cascades its outline/progress.
Cloudflare uses the existing same-origin API proxy and session cookie. No new
required environment variable, browser runtime or deployment configuration is
introduced. `SAPLING_MODEL_TOPIC_CHECKLIST` is an optional model override.

Hermetic tests cover authorization, enrollment/semester isolation, source IDs,
encryption, cache invalidation, progress persistence, review ordering and frontend
retry/race behavior. The opt-in local integration test checks real storage and
cascades. The Playwright journey checks the knowledge-map entry point and reload
persistence; the ciphertext/orphan oracles include the new tables. Run the local
integration and Playwright lanes against the disposable E2E stack, which resets
its database between tests.
