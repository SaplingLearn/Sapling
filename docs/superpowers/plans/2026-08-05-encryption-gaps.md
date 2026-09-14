# Encryption Coverage Gaps (#522) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four encryption-gap child issues of epic #522 as a stack of four PRs: #519 (documented plaintext exception), #520 (feedback + admin surface), #521 (quiz JSON), #518 (derived content).

**Architecture:** Every change follows the one existing boundary pattern — `encrypt_if_present`/`encrypt_json` at the write boundary, `decrypt_if_present`/a new `decrypt_json_column` guard at the read boundary. No schema migrations. Rollout-safe because code lands before backfill and every read path tolerates both plaintext (legacy) and ciphertext rows. Spec: `docs/superpowers/specs/2026-08-05-encryption-gaps-design.md`.

**Tech Stack:** FastAPI, PostgREST via `db/connection.py::table()`, AES-256-GCM via `backend/services/encryption.py`, pytest (hermetic mocks in `tests/conftest.py`), React/Next admin portal, Playwright/oracles e2e lanes.

## Global Constraints

- All backend commands run from `backend/` using the primary checkout's venv (`venv/bin/python`). Never unset `GEMINI_API_KEY`.
- Branch stack: `main ← feat/522-a-519-newsletter-adr ← feat/522-b-520-feedback ← feat/522-c-521-quiz ← feat/522-d-518-derived`. Each PR's base is the previous branch.
- Never touch `db/migrations/` — this epic has zero schema migrations.
- All Supabase access via `db/connection.py::table()`; encryption helpers only from `services/encryption.py`.
- Commit messages reference the child issue (`(#520)` etc.); PR bodies say `Closes #<issue>` and end with the Claude Code attribution line.
- The e2e stack is a machine singleton: any `make e2e-up` → test → `make e2e-down` cycle wraps in ONE `flock /tmp/claude-1000/sapling-e2e-stack.lock` invocation, with `SAPLING_MODEL_MODE=function` and `SAPLING_FUNCTION_HANDLERS` exported as `e2e.yml` does.
- `/code-review` runs on each PR before its merge (CodeRabbit skips stacked PRs, so this is the only real review for B–D).
- Existing tests with plaintext dict/str fixtures must keep passing — they double as the legacy-row coverage.

---

### Task 1: PR A — ADR 0026 + CLAUDE.md exception line (#519)

**Files:**
- Create: `docs/decisions/0026-newsletter-email-plaintext.md`
- Modify: `CLAUDE.md` (Gotchas section, after the column-encryption bullet)
- Branch: `feat/522-a-519-newsletter-adr` (already exists, spec committed at `4d10530`)

**Interfaces:**
- Consumes: nothing.
- Produces: the documented exception later tasks' CLAUDE.md edits sit next to.

- [ ] **Step 1: Verify you are on the right branch**

Run: `git branch --show-current`
Expected: `feat/522-a-519-newsletter-adr`. If not: `git checkout feat/522-a-519-newsletter-adr`.

- [ ] **Step 2: Write the ADR**

Create `docs/decisions/0026-newsletter-email-plaintext.md`:

```markdown
# 0026: `newsletter_emails.email` stays plaintext, deliberately

- Status: accepted
- Date: 2026-08-05
- Relates to: #519 (this decision), #522 (encryption-coverage epic),
  ADR 0025 (chunk_text — the sibling decision), #231 (bucket lockdown)
- Supersedes: none

## Context

`users.email` is encrypted; `newsletter_emails.email` is not (#519). Same data
type, different answer, and nothing wrote down why. The table is 4 rows in
production and doubles as the beta-allowlist workflow: `routes/newsletter.py:27`
upserts on `email` at subscribe, and `routes/admin.py` lists/approves/revokes
by email value (`/api/admin/allowlist`).

`services/encryption.py` is AES-256-GCM with a fresh random nonce per call —
the same address never encrypts to the same bytes. Naive encryption therefore
breaks this table's `UNIQUE(email)` constraint, its lookup index, and both
upserts' conflict detection, silently converting dedupe into duplicate rows.

## Options considered

1. **Deterministic lookup column** — add `email_hash TEXT UNIQUE`
   (HMAC-SHA256 of the normalised address, key derived from `ENCRYPTION_KEY`),
   move the constraint/index/conflict targets to it, encrypt `email`.
   Preserves everything; costs a migration, a key-derivation seam, a rewrite
   of two routes, and a backfill.
2. **Leave plaintext, record the decision** (chosen).
3. **Stop storing it** — hand subscription to the newsletter sender.
   Rejected outright: it kills the admin allowlist workflow.

## Decision

Option 2. A subscription/allowlist address with no other user data attached is
the lowest-sensitivity personal field in the schema; the operational value of
a value-keyed UNIQUE table (dedupe, dashboard readability, trivial upserts) is
high; and the HMAC machinery of option 1 buys little at this sensitivity for a
4-row table. If this table ever grows richer user data or the beta gate is
retired, revisit option 1.

## Consequences

- `newsletter_emails.email` is an **intentional exception**, listed in
  CLAUDE.md next to the encrypted-columns gotcha, so the gap is not re-filed.
- The `users.email` inconsistency is now documented rather than silent, which
  is what #519 actually asked for.
- The e2e ciphertext oracle deliberately does NOT cover this column.
```

- [ ] **Step 3: Add the CLAUDE.md exception line**

In `CLAUDE.md`, in the Gotchas bullet that starts "Column-level encryption is on for sensitive columns:", append after "`ENCRYPTION_KEY` must be set (…)." this sentence:

```
Deliberate exception: `newsletter_emails.email` stays plaintext (ADR 0026) — the UNIQUE constraint, lookup index, and both subscribe/allowlist upserts key on the value, and AES-GCM's per-call nonce breaks value equality.
```

- [ ] **Step 4: Commit and push**

```bash
git add docs/decisions/0026-newsletter-email-plaintext.md CLAUDE.md
git commit -m "docs(adr): newsletter_emails.email plaintext-by-decision (#519)"
git push -u origin feat/522-a-519-newsletter-adr
```

- [ ] **Step 5: Open PR A against main**

```bash
gh pr create --base main --title "docs: newsletter email plaintext-by-decision ADR + encryption-gaps spec (#519)" --body "Closes #519.

Option 2 from the issue: \`newsletter_emails.email\` stays plaintext, deliberately —
the UNIQUE constraint, lookup index, and both upserts (subscribe + admin allowlist)
key on the email value, which AES-GCM's per-call nonce breaks. ADR 0026 records the
decision and the rejected HMAC alternative; CLAUDE.md names the exception so the gap
is not re-filed. Also carries the approved design spec for the #522 stack.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 2: PR B — encrypt feedback/issue_reports at write (#520)

**Files:**
- Modify: `backend/routes/feedback.py:35-44,55-62` (the two inserts) + imports
- Test: `backend/tests/test_feedback_routes.py` (extend)
- Branch: create `feat/522-b-520-feedback` off `feat/522-a-519-newsletter-adr`

**Interfaces:**
- Consumes: `services.encryption.encrypt_if_present(value) -> str | None`, `decrypt(value) -> str`.
- Produces: `feedback.comment/topic` and `issue_reports.topic/description` are ciphertext in every insert payload. Task 3's admin reads and Task 5's backfill/seed rely on exactly these four columns being the encrypted set.

- [ ] **Step 1: Create the branch**

```bash
git checkout feat/522-a-519-newsletter-adr && git checkout -b feat/522-b-520-feedback
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_feedback_routes.py` (reuse the module's existing `_factory` recorder and `client`):

```python
class TestFeedbackEncryption:
    """#520: free-text user input is ciphertext at rest."""

    def test_feedback_comment_and_topic_encrypted(self):
        from services.encryption import decrypt
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/feedback",
                json={
                    "user_id": "user_andres",
                    "type": "global",
                    "rating": 4,
                    "selected_options": ["tutor"],
                    "comment": "The tutor cited the wrong lecture",
                    "topic": "chat",
                },
            )
        assert r.status_code == 200
        (name, row), = recorded
        assert name == "feedback"
        # Ciphertext at rest…
        assert row["comment"] != "The tutor cited the wrong lecture"
        assert row["topic"] != "chat"
        # …that round-trips.
        assert decrypt(row["comment"]) == "The tutor cited the wrong lecture"
        assert decrypt(row["topic"]) == "chat"
        # Enum/scalar columns stay queryable plaintext.
        assert row["type"] == "global"
        assert row["rating"] == 4
        assert row["selected_options"] == ["tutor"]

    def test_feedback_none_comment_stays_none(self):
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/feedback",
                json={"user_id": "user_andres", "type": "global", "rating": 5},
            )
        assert r.status_code == 200
        (_, row), = recorded
        assert row["comment"] is None
        assert row["topic"] is None

    def test_issue_report_topic_and_description_encrypted(self):
        from services.encryption import decrypt
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/issue-reports",
                json={
                    "user_id": "user_andres",
                    "topic": "upload stuck",
                    "description": "Syllabus upload spins forever",
                    "screenshot_urls": ["u1/a.png"],
                },
            )
        assert r.status_code == 200
        (name, row), = recorded
        assert name == "issue_reports"
        assert row["topic"] != "upload stuck"
        assert row["description"] != "Syllabus upload spins forever"
        assert decrypt(row["topic"]) == "upload stuck"
        assert decrypt(row["description"]) == "Syllabus upload spins forever"
        assert row["screenshot_urls"] == ["u1/a.png"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_feedback_routes.py -q`
Expected: the three new tests FAIL on the `!=` assertions (values are still plaintext); existing tests PASS.

- [ ] **Step 4: Implement**

In `backend/routes/feedback.py` add to imports:

```python
from services.encryption import encrypt_if_present
```

In `submit_feedback`, change the insert's two free-text fields:

```python
        "comment": encrypt_if_present(body.comment),
        ...
        "topic": encrypt_if_present(body.topic),
```

In `submit_issue_report`:

```python
        "topic": encrypt_if_present(body.topic),
        "description": encrypt_if_present(body.description),
```

(`encrypt_if_present(None)` returns `None`, so optional fields keep their NULL semantics.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_feedback_routes.py -q`
Expected: all PASS. Then prove fail-on-revert: `git stash && venv/bin/python -m pytest tests/test_feedback_routes.py -q` → new tests FAIL; `git stash pop`.

- [ ] **Step 6: Commit**

```bash
git add routes/feedback.py tests/test_feedback_routes.py
git commit -m "feat(feedback): encrypt comment/topic/description at write (#520)"
```

---

### Task 3: PR B — admin read endpoints for feedback + issue reports

**Files:**
- Modify: `backend/routes/admin.py` (imports + two new GET routes, place after `revoke_allowlist`)
- Test: `backend/tests/test_admin_routes.py` (extend)

**Interfaces:**
- Consumes: Task 2's guarantee that `comment`/`topic`/`description` are ciphertext; `services.profiles.get_display_names(ids: list[str]) -> dict[str, str]`; `services.encryption.decrypt_if_present`.
- Produces: `GET /api/admin/feedback` → `{"feedback": [{id, user_id, user_name, type, rating, selected_options, comment, session_id, topic, created_at}]}` and `GET /api/admin/issue-reports` → `{"reports": [{id, user_id, user_name, topic, description, screenshot_urls, created_at}]}`, both `require_admin`-gated, newest first, decrypted. Task 4's frontend consumes exactly these shapes.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_admin_routes.py` (uses the module's existing `client` and `_mock_admin`):

```python
# ── GET /api/admin/feedback + /api/admin/issue-reports (#520) ──────────────

class TestAdminFeedbackReads:
    def test_list_feedback_decrypts_and_names(self):
        from services.encryption import encrypt
        rows = [{
            "id": "fb1", "user_id": "u1", "type": "global", "rating": 4,
            "selected_options": ["tutor"], "comment": encrypt("wrong lecture"),
            "session_id": None, "topic": encrypt("chat"),
            "created_at": "2026-08-05T00:00:00Z",
        }]
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_display_names", return_value={"u1": "Rich Active"}):
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/feedback")
        assert r.status_code == 200
        entry = r.json()["feedback"][0]
        assert entry["comment"] == "wrong lecture"
        assert entry["topic"] == "chat"
        assert entry["user_name"] == "Rich Active"
        assert entry["rating"] == 4

    def test_list_feedback_tolerates_legacy_plaintext_rows(self):
        rows = [{
            "id": "fb0", "user_id": "u1", "type": "global", "rating": 2,
            "selected_options": [], "comment": "pre-backfill plaintext",
            "session_id": None, "topic": None, "created_at": "2026-08-01T00:00:00Z",
        }]
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_display_names", return_value={}):
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/feedback")
        assert r.status_code == 200
        assert r.json()["feedback"][0]["comment"] == "pre-backfill plaintext"

    def test_list_issue_reports_decrypts(self):
        from services.encryption import encrypt
        rows = [{
            "id": "ir1", "user_id": "u1", "topic": encrypt("upload stuck"),
            "description": encrypt("spins forever"),
            "screenshot_urls": ["u1/a.png"], "created_at": "2026-08-05T00:00:00Z",
        }]
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_display_names", return_value={"u1": "Rich Active"}):
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/issue-reports")
        assert r.status_code == 200
        rep = r.json()["reports"][0]
        assert rep["topic"] == "upload stuck"
        assert rep["description"] == "spins forever"
        assert rep["screenshot_urls"] == ["u1/a.png"]

    def test_feedback_requires_admin(self):
        with patch("routes.admin.require_admin",
                   side_effect=HTTPException(status_code=403, detail="nope")):
            assert client.get("/api/admin/feedback").status_code == 403
            assert client.get("/api/admin/issue-reports").status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_admin_routes.py::TestAdminFeedbackReads -q`
Expected: 404s — the routes don't exist.

- [ ] **Step 3: Implement the two routes**

In `backend/routes/admin.py` add imports:

```python
from services.encryption import decrypt_if_present
from services.profiles import get_display_names
```

After `revoke_allowlist`, add:

```python
# ── Feedback + issue reports (#520) ──────────────────────────────────────────
# These tables are 🔒 at rest (comment/topic/description); the Supabase
# dashboard shows ciphertext, so this is the only human-readable surface.

@router.get("/feedback")
def list_feedback(request: Request, limit: int = 200):
    require_admin(request)
    rows = table("feedback").select(
        "id,user_id,type,rating,selected_options,comment,session_id,topic,created_at",
        order="created_at.desc",
        limit=max(1, min(int(limit), 500)),
    ) or []
    names = get_display_names([r["user_id"] for r in rows])
    for r in rows:
        r["comment"] = decrypt_if_present(r.get("comment"))
        r["topic"] = decrypt_if_present(r.get("topic"))
        r["user_name"] = names.get(r["user_id"], "")
    return {"feedback": rows}


@router.get("/issue-reports")
def list_issue_reports(request: Request, limit: int = 200):
    require_admin(request)
    rows = table("issue_reports").select(
        "id,user_id,topic,description,screenshot_urls,created_at",
        order="created_at.desc",
        limit=max(1, min(int(limit), 500)),
    ) or []
    names = get_display_names([r["user_id"] for r in rows])
    for r in rows:
        r["topic"] = decrypt_if_present(r.get("topic"))
        r["description"] = decrypt_if_present(r.get("description"))
        r["user_name"] = names.get(r["user_id"], "")
    return {"reports": rows}
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/test_admin_routes.py -q`
Expected: all PASS (new and pre-existing).

- [ ] **Step 5: Commit**

```bash
git add routes/admin.py tests/test_admin_routes.py
git commit -m "feat(admin): decrypting read endpoints for feedback + issue reports (#520)"
```

---

### Task 4: PR B — admin portal "feedback" tab

**Files:**
- Modify: `frontend/src/lib/api.ts` (after the Admin — users block, ~line 1020)
- Modify: `frontend/src/components/screens/Admin.tsx` (`Tab` union :26, tabs array :58, render block :88-94, new `FeedbackTab` component at end)
- Modify: `docs/frontend-testids.md` (inventory + prefix table per "Adding a surface")

**Interfaces:**
- Consumes: Task 3's exact response shapes.
- Produces: `adminListFeedback()`, `adminListIssueReports()` in `lib/api.ts`; a `feedback` tab in the admin portal.

- [ ] **Step 1: Add fetchers + types to `frontend/src/lib/api.ts`**

```ts
// Admin — feedback (#520; decrypted server-side, admin-only)
export type AdminFeedbackEntry = {
  id: string; user_id: string; user_name: string; type: string; rating: number;
  selected_options: string[]; comment: string | null; session_id: string | null;
  topic: string | null; created_at: string;
};
export type AdminIssueReport = {
  id: string; user_id: string; user_name: string; topic: string;
  description: string; screenshot_urls: string[]; created_at: string;
};
export const adminListFeedback = () =>
  fetchJSON<{ feedback: AdminFeedbackEntry[] }>('/api/admin/feedback');
export const adminListIssueReports = () =>
  fetchJSON<{ reports: AdminIssueReport[] }>('/api/admin/issue-reports');
```

- [ ] **Step 2: Add the tab to `Admin.tsx`**

Extend the union and list (`:26`, `:58`) with `"feedback"`, add `{tab === "feedback" && <FeedbackTab />}` to the render block, extend the api import with `adminListFeedback, adminListIssueReports, AdminFeedbackEntry, AdminIssueReport`, and add at the end of the file (mirrors `AllowlistTab`'s load/skeleton/toast conventions):

```tsx
function FeedbackTab() {
  const toast = useToast();
  const [feedback, setFeedback] = React.useState<AdminFeedbackEntry[]>([]);
  const [reports, setReports] = React.useState<AdminIssueReport[]>([]);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    try {
      const [f, r] = await Promise.all([adminListFeedback(), adminListIssueReports()]);
      setFeedback(f.feedback || []);
      setReports(r.reports || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  if (loading) return <AdminTableSkeleton />;

  const when = (iso: string) => new Date(iso).toLocaleDateString();

  return (
    <>
      <div className="card" style={{ padding: 0, marginBottom: 22 }} data-testid="adminfb-feedback-card">
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
          Feedback ({feedback.length})
        </div>
        {feedback.length === 0 && (
          <div style={{ padding: 16, color: "var(--text-dim)" }}>No feedback yet.</div>
        )}
        {feedback.map((f) => (
          <div key={f.id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }} data-testid="adminfb-feedback-row">
            <div style={{ display: "flex", gap: 12, color: "var(--text-dim)", fontSize: 13 }}>
              <span>{when(f.created_at)}</span>
              <span style={{ color: "var(--text)" }}>{f.user_name || f.user_id}</span>
              <span>{f.type}</span>
              <span>{"★".repeat(f.rating)}{"☆".repeat(Math.max(0, 5 - f.rating))}</span>
              {f.topic && <span>{f.topic}</span>}
            </div>
            {f.comment && <div style={{ marginTop: 6 }}>{f.comment}</div>}
            {f.selected_options.length > 0 && (
              <div style={{ marginTop: 4, fontSize: 13, color: "var(--text-dim)" }}>
                {f.selected_options.join(" · ")}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="card" style={{ padding: 0 }} data-testid="adminfb-issues-card">
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>
          Issue reports ({reports.length})
        </div>
        {reports.length === 0 && (
          <div style={{ padding: 16, color: "var(--text-dim)" }}>No issue reports yet.</div>
        )}
        {reports.map((r) => (
          <div key={r.id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }} data-testid="adminfb-issue-row">
            <div style={{ display: "flex", gap: 12, color: "var(--text-dim)", fontSize: 13 }}>
              <span>{when(r.created_at)}</span>
              <span style={{ color: "var(--text)" }}>{r.user_name || r.user_id}</span>
              <span>{r.topic}</span>
              {r.screenshot_urls.length > 0 && <span>{r.screenshot_urls.length} screenshot(s)</span>}
            </div>
            <div style={{ marginTop: 6 }}>{r.description}</div>
          </div>
        ))}
      </div>
    </>
  );
}
```

- [ ] **Step 3: Register testids**

Per `docs/frontend-testids.md` "Adding a surface": add the `adminfb-` prefix row to the table, add the four testids to the inventory. `Admin.tsx` is already in the lint `files` array (it carries other tabs' testids) — if `npm run lint` flags additional interactive elements, give them `adminfb-*` ids.

- [ ] **Step 4: Frontend gates**

Run from `frontend/`: `npm run lint && npm run typecheck && npm test`
Expected: all pass. If lint exits 2 about suppressions, run `npx eslint . --prune-suppressions` and commit the baseline change (per the ratchet convention).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/screens/Admin.tsx ../docs/frontend-testids.md
git commit -m "feat(admin-ui): feedback tab reading the decrypted admin endpoints (#520)"
```

---

### Task 5: PR B — backfill, seed, roundtrip, oracle, CLAUDE.md for #520's columns

**Files:**
- Modify: `backend/db/backfill_encryption.py` (two runners + `RUNNERS` registry)
- Modify: `backend/db/seed_local_rich.py` (new `_FEEDBACK`/`_ISSUE_REPORTS` + seeder + `_SUMMARY_ORDER` + main call)
- Modify: `backend/e2e_oracles/gather.py` (`_CIPHERTEXT_MANIFEST`)
- Modify: `backend/tests/integration/test_encryption_roundtrip.py` (`_TEXT_COLUMNS`)
- Modify: `CLAUDE.md` (encrypted-columns gotcha)

**Interfaces:**
- Consumes: `_encrypt_text_column(table, columns, *, pk="id", apply)`; `h.insert_if_absent(table, id, row)`; seed constants `USER_ACTIVE`.
- Produces: `RUNNERS["feedback"]`, `RUNNERS["issue_reports"]`; seeded rows `rich-fb-1`, `rich-issue-1` with known plaintext (used verbatim by the roundtrip entries below).

- [ ] **Step 1: Backfill runners**

In `backend/db/backfill_encryption.py`, after `backfill_room_messages`:

```python
def backfill_feedback(apply: bool) -> dict:
    return _encrypt_text_column("feedback", ["comment", "topic"], pk="id", apply=apply)


def backfill_issue_reports(apply: bool) -> dict:
    return _encrypt_text_column(
        "issue_reports", ["topic", "description"], pk="id", apply=apply
    )
```

Register in `RUNNERS`:

```python
    "feedback": backfill_feedback,
    "issue_reports": backfill_issue_reports,
```

- [ ] **Step 2: Seed rows (encrypted, like `room_messages`' `encrypt_if_present` usage at seed line 488)**

In `backend/db/seed_local_rich.py` after `seed_quiz()`'s definitions:

```python
# #520: feedback/issue_reports are 🔒 (comment/topic/description) — seed them
# encrypted so the roundtrip test + ciphertext oracle have baseline rows.
def seed_feedback() -> None:
    h.insert_if_absent(
        "feedback",
        "rich-fb-1",
        {
            "user_id": USER_ACTIVE,
            "type": "global",
            "rating": 4,
            "selected_options": ["tutor"],
            "comment": encrypt_if_present("The tutor cited the wrong lecture."),
            "topic": encrypt_if_present("chat"),
        },
    )
    h.insert_if_absent(
        "issue_reports",
        "rich-issue-1",
        {
            "user_id": USER_ACTIVE,
            "topic": encrypt_if_present("Upload stuck"),
            "description": encrypt_if_present("Syllabus upload spins forever."),
            "screenshot_urls": [],
        },
    )
```

Add `"feedback", "issue_reports"` to `_SUMMARY_ORDER` (after `"messages"`) and call `seed_feedback()` in `main()` after `seed_quiz()`.

- [ ] **Step 3: Roundtrip entries**

In `backend/tests/integration/test_encryption_roundtrip.py` append to `_TEXT_COLUMNS`:

```python
    ("feedback.comment", "feedback", "id", "rich-fb-1", "comment",
     "The tutor cited the wrong lecture."),
    ("feedback.topic", "feedback", "id", "rich-fb-1", "topic", "chat"),
    ("issue_reports.topic", "issue_reports", "id", "rich-issue-1", "topic",
     "Upload stuck"),
    ("issue_reports.description", "issue_reports", "id", "rich-issue-1",
     "description", "Syllabus upload spins forever."),
```

- [ ] **Step 4: Ciphertext oracle manifest**

In `backend/e2e_oracles/gather.py` append to `_CIPHERTEXT_MANIFEST`:

```python
    ("feedback", "id", "comment"),
    ("feedback", "id", "topic"),
    ("issue_reports", "id", "topic"),
    ("issue_reports", "id", "description"),
)
```

- [ ] **Step 5: CLAUDE.md**

In the encrypted-columns gotcha, extend the list with: `feedback.comment`/`topic` and `issue_reports.topic`/`description` (free-text user input, #520).

- [ ] **Step 6: Backend suite + backfill dry-run smoke**

Run: `venv/bin/python -m pytest tests/ -q` → all pass.
Run: `venv/bin/python -m db.backfill_encryption --table feedback --table issue_reports` (dry run against local) → prints counts, no crash.

- [ ] **Step 7: Commit, push, open PR B**

```bash
git add db/backfill_encryption.py db/seed_local_rich.py e2e_oracles/gather.py tests/integration/test_encryption_roundtrip.py ../CLAUDE.md
git commit -m "feat(ops): backfill/seed/oracle/roundtrip coverage for feedback encryption (#520)"
git push -u origin feat/522-b-520-feedback
gh pr create --base feat/522-a-519-newsletter-adr --title "feat(feedback): encrypt free-text input + admin read surface (#520)" --body "Closes #520.

- \`feedback.comment/topic\`, \`issue_reports.topic/description\` encrypted at write
- NEW admin surface (the app had no reader; the dashboard goes blind): GET /api/admin/feedback + /api/admin/issue-reports and a portal feedback tab
- backfill runners, encrypted seed rows, roundtrip tests, ciphertext-oracle manifest entries
- rollout-safe: reads tolerate pre-backfill plaintext rows (tested)

Stacked on #519's ADR PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 6: PR C — `decrypt_json_column` read-boundary guard

**Files:**
- Modify: `backend/services/encryption.py` (one function, after `decrypt_json`)
- Test: `backend/tests/test_encryption_json_column.py` (create)
- Branch: create `feat/522-c-521-quiz` off `feat/522-b-520-feedback`

**Interfaces:**
- Consumes: `decrypt_json(value: str) -> dict | list`.
- Produces: `decrypt_json_column(value: Any) -> Any` — None → None; dict/list (legacy plaintext JSONB) → unchanged; str → `decrypt_json` (which itself falls back to `json.loads` for plaintext JSON strings). Tasks 7, 11, 12 call exactly this name.

- [ ] **Step 1: Create the branch**

```bash
git checkout feat/522-b-520-feedback && git checkout -b feat/522-c-521-quiz
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_encryption_json_column.py`:

```python
"""decrypt_json_column: the read-boundary guard for JSONB columns that may
hold legacy plaintext (dict/list from PostgREST) or ciphertext (str). #521."""
from services.encryption import decrypt_json_column, encrypt_json


def test_none_passes_through():
    assert decrypt_json_column(None) is None


def test_legacy_plaintext_dict_passes_through():
    v = {"asked": 3, "misconceptions": ["off-by-one"]}
    assert decrypt_json_column(v) is v


def test_legacy_plaintext_list_passes_through():
    v = [{"q": "Q1"}]
    assert decrypt_json_column(v) is v


def test_ciphertext_string_decrypts():
    payload = {"asked": 3, "misconceptions": ["off-by-one"]}
    assert decrypt_json_column(encrypt_json(payload)) == payload


def test_plaintext_json_string_falls_back():
    # A TEXT-era row that stored raw JSON — decrypt_json's fallback parses it.
    assert decrypt_json_column('{"a": 1}') == {"a": 1}
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_encryption_json_column.py -q`
Expected: ImportError — `decrypt_json_column` not defined.

- [ ] **Step 4: Implement**

In `backend/services/encryption.py` after `decrypt_json`:

```python
def decrypt_json_column(value: Any) -> Any:
    """Read-boundary guard for JSON columns that may hold either legacy
    plaintext JSONB (arrives as dict/list) or ciphertext (str). #521/#518."""
    if value is None or isinstance(value, (dict, list)):
        return value
    return decrypt_json(value)
```

- [ ] **Step 5: Run to verify pass, then commit**

Run: `venv/bin/python -m pytest tests/test_encryption_json_column.py -q` → PASS.

```bash
git add services/encryption.py tests/test_encryption_json_column.py
git commit -m "feat(encryption): decrypt_json_column read-boundary guard (#521)"
```

---

### Task 7: PR C — encrypt quiz writes, decrypt quiz reads (#521)

**Files:**
- Modify: `backend/routes/quiz.py` (insert ~:352, submit read ~:383, score update ~:486, imports)
- Modify: `backend/services/quiz_context_service.py` (both functions)
- Modify: `backend/agents/tools/quiz_history.py` (`_fetch_summary`)
- Modify: `backend/services/course_context_service.py` (`_parse_quiz_context_to_arrays`)
- Test: `backend/tests/test_quiz_routes.py`, `backend/tests/test_quiz_history_tool.py` (extend)

**Interfaces:**
- Consumes: `encrypt_json`, `decrypt_json_column` (Task 6).
- Produces: `quiz_attempts.questions_json`/`answers_json` and `quiz_context.context_json` are ciphertext strings in every write payload; every reader hands plaintext dicts/lists onward. Task 8's backfill/seed target exactly these three columns.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_quiz_routes.py`, following that module's existing mock style (patch `routes.quiz.table` and whatever agent/`require_self` mocks its generate/submit tests already use — copy the arrange blocks from the nearest existing test in the file):

```python
class TestQuizEncryption:
    """#521: quiz JSON payloads are ciphertext at rest, plaintext in responses."""

    def test_generate_inserts_encrypted_questions(self):
        # Arrange exactly as the module's existing generate-quiz test does
        # (agent mock returning a fixed Quiz), recording quiz_attempts.insert.
        # Assert on the recorded insert payload:
        from services.encryption import decrypt_json_column
        row = recorded_insert  # the captured quiz_attempts.insert payload
        assert isinstance(row["questions_json"], str)
        decrypted = decrypt_json_column(row["questions_json"])
        assert isinstance(decrypted, list) and decrypted
        # Scalars stay plaintext:
        assert row["difficulty"] in ("easy", "medium", "hard")

    def test_submit_decrypts_encrypted_questions_and_encrypts_answers(self):
        from services.encryption import encrypt_json, decrypt_json_column
        questions = [{"id": 1, "question": "Q1", "options": [
            {"label": "A", "text": "yes"}], "correct_label": "A"}]
        attempt = {
            "id": "qz1", "user_id": "u1", "concept_node_id": "n1",
            "questions_json": encrypt_json(questions),   # ciphertext at rest
            "completed_at": None, "difficulty": "easy",
        }
        # Arrange as the module's existing submit test does (attempt select
        # returns [attempt]; graph mocks as-is). Then:
        # - the response scores against the DECRYPTED questions (Q1 present),
        # - the recorded answers_json update payload is a ciphertext str that
        #   decrypt_json_column round-trips to the submitted answers.

    def test_submit_still_accepts_legacy_plaintext_questions(self):
        # Same arrangement but questions_json stored as the raw list —
        # the pre-backfill row shape. Must score identically.
        ...
```

Append to `backend/tests/test_quiz_history_tool.py`:

```python
def test_summary_decrypts_encrypted_context():
    from services.encryption import encrypt_json
    # Arrange as the module's existing summary test (patch the table factory);
    # quiz_context select returns
    #   [{"context_json": encrypt_json({"misconceptions": ["off-by-one"]})}]
    # Assert the tool's returned summary contains the plaintext payload,
    # not a base64 string.
```

Write these as real tests by copying each module's existing arrange/mock blocks — the sketches above define the assertions; the surrounding fixtures already exist in the two files.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `venv/bin/python -m pytest tests/test_quiz_routes.py tests/test_quiz_history_tool.py -q`
Expected: new tests FAIL (plaintext inserts / ciphertext leaking); existing tests PASS.

- [ ] **Step 3: Implement — `routes/quiz.py`**

Add to imports:

```python
from services.encryption import encrypt_json, decrypt_json_column
```

Insert site (~:352): `"questions_json": encrypt_json(questions),`

Submit read (~:383) — replace:

```python
    questions = attempt["questions_json"]
    if isinstance(questions, str):
        questions = json.loads(questions)
```

with:

```python
    # #521: ciphertext str for new rows, plaintext JSONB for pre-backfill rows.
    questions = decrypt_json_column(attempt["questions_json"])
```

Score update (~:486): `"answers_json": encrypt_json([a.model_dump() for a in body.answers]),`

- [ ] **Step 4: Implement — the three other readers/writers**

`services/quiz_context_service.py`:

```python
from services.encryption import encrypt_json, decrypt_json_column
...
    if rows:
        return decrypt_json_column(rows[0]["context_json"])
...
            "context_json": encrypt_json(context),
```

`agents/tools/quiz_history.py` `_fetch_summary`:

```python
            return decrypt_json_column(rows[0]["context_json"]) if rows else None
```

(add `from services.encryption import decrypt_json_column` to that module's imports).

`services/course_context_service.py` `_parse_quiz_context_to_arrays` — replace the `isinstance(cj, str)` + `json.loads` block with:

```python
            from services.encryption import decrypt_json_column
            cj = ctx.get("context_json") or {}
            try:
                cj = decrypt_json_column(cj) or {}
            except Exception:
                cj = {}
```

(keep the module's existing local-import style if it imports at top level — then move the import to the top; decrypt happens here, BEFORE the lru-cached context object is assembled, so the cache holds plaintext exactly as before.)

- [ ] **Step 5: Run the full backend suite**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: all PASS — including untouched older quiz tests whose plaintext fixtures now exercise the legacy branch.

- [ ] **Step 6: Commit**

```bash
git add routes/quiz.py services/quiz_context_service.py agents/tools/quiz_history.py services/course_context_service.py tests/test_quiz_routes.py tests/test_quiz_history_tool.py
git commit -m "feat(quiz): encrypt questions/answers/context JSON at rest (#521)"
```

---

### Task 8: PR C — backfill, seed, roundtrip, oracle, CLAUDE.md for #521's columns

**Files:**
- Modify: `backend/db/backfill_encryption.py`, `backend/db/seed_local_rich.py`, `backend/e2e_oracles/gather.py`, `backend/tests/integration/test_encryption_roundtrip.py`, `CLAUDE.md`

**Interfaces:**
- Consumes: `_encrypt_json_column(table, column, *, pk="id", apply)`; seed's `encrypt_json` import; `_QUIZ_ATTEMPTS` seed data.
- Produces: `RUNNERS["quiz_attempts"]`, `RUNNERS["quiz_context"]`; seeded `quiz_context` row `rich-qc-cs-variables`.

- [ ] **Step 1: Backfill runners**

```python
def backfill_quiz_attempts(apply: bool) -> dict:
    q = _encrypt_json_column("quiz_attempts", "questions_json", pk="id", apply=apply)
    a = _encrypt_json_column("quiz_attempts", "answers_json", pk="id", apply=apply)
    return {
        "scanned": q["scanned"],
        "questions_json": q["questions_json"],
        "answers_json": a["answers_json"],
    }


def backfill_quiz_context(apply: bool) -> dict:
    return _encrypt_json_column("quiz_context", "context_json", pk="id", apply=apply)
```

Register `"quiz_attempts"` and `"quiz_context"` in `RUNNERS`.

- [ ] **Step 2: Seed — encrypt the existing quiz payloads + add a quiz_context row**

In `seed_quiz()`, wrap the JSON payloads (`encrypt_json` is already imported at seed line 22):

```python
                "questions_json": encrypt_json(questions),
                "answers_json": encrypt_json(answers) if answers is not None else None,
```

After the loop, add:

```python
    # #521: quiz_context is 🔒 — one row so the roundtrip test has a baseline.
    h.insert_if_absent(
        "quiz_context",
        "rich-qc-cs-variables",
        {
            "user_id": USER_ACTIVE,
            "concept_node_id": "rich-node-cs-variables",
            "context_json": encrypt_json(
                {"misconceptions": ["confuses = with =="], "asked": 2}
            ),
        },
    )
```

Add `"quiz_context"` to `_SUMMARY_ORDER` after `"quiz_attempts"`.

- [ ] **Step 3: Roundtrip tests (JSON style, mirroring `test_sessions_summary_json_…`)**

```python
def test_quiz_attempts_questions_json_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "quiz_attempts", "id", "rich-qa-cs-variables-1", "questions_json")
    assert raw is not None
    assert isinstance(raw, str), "questions_json stored as PLAINTEXT JSONB — encryption regressed"
    decoded = decrypt_json(raw)
    assert decoded[0]["q"] == "What keyword declares a variable in Python?"


def test_quiz_attempts_answers_json_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "quiz_attempts", "id", "rich-qa-cs-variables-1", "answers_json")
    assert isinstance(raw, str)
    assert decrypt_json(raw)[0]["correct"] is True


def test_quiz_context_context_json_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "quiz_context", "id", "rich-qc-cs-variables", "context_json")
    assert isinstance(raw, str)
    decoded = decrypt_json(raw)
    assert decoded["asked"] == 2
```

(psycopg returns a JSONB-stored JSON string as a Python `str`, and a JSONB object as `dict` — the `isinstance(raw, str)` assert IS the ciphertext-at-rest check.)

- [ ] **Step 4: Oracle manifest + CLAUDE.md**

Manifest additions: `("quiz_attempts", "id", "questions_json")`, `("quiz_attempts", "id", "answers_json")`, `("quiz_context", "id", "context_json")`.
CLAUDE.md: extend the encrypted list with `quiz_attempts.questions_json`/`answers_json` and `quiz_context.context_json` (quiz performance data, #521; scalars stay plaintext for analytics).

- [ ] **Step 5: Suite + dry-run + commit + PR**

Run: `venv/bin/python -m pytest tests/ -q` → PASS.
Run: `venv/bin/python -m db.backfill_encryption --table quiz_attempts --table quiz_context` → dry-run counts.

```bash
git add db/backfill_encryption.py db/seed_local_rich.py e2e_oracles/gather.py tests/integration/test_encryption_roundtrip.py ../CLAUDE.md
git commit -m "feat(ops): backfill/seed/oracle/roundtrip coverage for quiz encryption (#521)"
git push -u origin feat/522-c-521-quiz
gh pr create --base feat/522-b-520-feedback --title "feat(quiz): encrypt quiz performance JSON at rest (#521)" --body "Closes #521.

- \`quiz_attempts.questions_json/answers_json\` + \`quiz_context.context_json\` via encrypt_json, matching sessions.summary_json
- decrypt at all four readers (submit scoring, quiz_context_service, quiz_history agent tool, course_context) — always before prompts and before the lru cache
- scalars (score/total/difficulty/completed_at) untouched; analytics unaffected
- new decrypt_json_column guard: legacy plaintext JSONB rows keep working pre-backfill (tested)
- backfill runners, encrypted seed, roundtrip tests, ciphertext-oracle entries

Stacked on #520's PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 9: PR D — flashcards front/back (#518)

**Files:**
- Modify: `backend/routes/flashcards.py` (both insert row-builders ~:235-246 and ~:395-406; list read ~:290; imports)
- Modify: `backend/services/flashcard_import_service.py` (`dedup_against_existing` ~:78)
- Test: `backend/tests/test_flashcards_routes.py`, `backend/tests/test_flashcard_import_service.py` (extend)
- Branch: create `feat/522-d-518-derived` off `feat/522-c-521-quiz`

**Interfaces:**
- Consumes: `encrypt_if_present`, `decrypt_if_present`.
- Produces: `flashcards.front`/`back` ciphertext in every insert; list responses plaintext; dedupe still works over ciphertext rows. Task 12's backfill/seed target these two columns.

- [ ] **Step 1: Create the branch**

```bash
git checkout feat/522-c-521-quiz && git checkout -b feat/522-d-518-derived
```

- [ ] **Step 2: Write the failing tests**

`tests/test_flashcards_routes.py` — following that module's existing mock style (copy its generate-flashcards arrange block; it records inserts):

```python
class TestFlashcardEncryption:
    def test_generated_cards_encrypted_at_write(self):
        from services.encryption import decrypt
        # Arrange per the module's existing generation test; then for every
        # recorded flashcards.insert row:
        assert row["front"] != plaintext_front
        assert decrypt(row["front"]) == plaintext_front
        assert decrypt(row["back"]) == plaintext_back
        # topic stays plaintext (it's a filter column):
        assert row["topic"] == plaintext_topic

    def test_list_decrypts_front_and_back(self):
        from services.encryption import encrypt
        # select returns rows with front/back = encrypt("Q")/encrypt("A");
        # the JSON response must contain "Q"/"A".

    def test_list_tolerates_legacy_plaintext_rows(self):
        # select returns plaintext front/back; response identical.
```

`tests/test_flashcard_import_service.py`:

```python
def test_dedup_matches_against_encrypted_existing_cards():
    from services.encryption import encrypt
    # existing select returns [{"front": encrypt("What is a variable?")}];
    # importing a card with front "What is a variable?" must be SKIPPED.


def test_dedup_still_matches_legacy_plaintext_rows():
    # existing select returns [{"front": "What is a variable?"}]; same skip.
```

Write them as real tests using each module's existing fixtures/factories.

- [ ] **Step 3: Run to verify the new tests fail**

Run: `venv/bin/python -m pytest tests/test_flashcards_routes.py tests/test_flashcard_import_service.py -q`

- [ ] **Step 4: Implement**

`routes/flashcards.py` — add `encrypt_if_present` to the existing `services.encryption` import; in BOTH row-builder list comprehensions:

```python
            "front": encrypt_if_present(c["front"]),
            "back": encrypt_if_present(c["back"]),
```

In the list read (after the `select` ~:290, before term filtering returns):

```python
        for r in rows:
            r["front"] = decrypt_if_present(r.get("front"))
            r["back"] = decrypt_if_present(r.get("back"))
```

`services/flashcard_import_service.py`:

```python
from services.encryption import decrypt_if_present
...
    existing_norm = [
        _normalize(decrypt_if_present(r.get("front", "")) or "") for r in existing
    ]
```

- [ ] **Step 5: Run, verify, commit**

Run: `venv/bin/python -m pytest tests/test_flashcards_routes.py tests/test_flashcard_import_service.py tests/test_flashcard_import_routes.py -q` → PASS.

```bash
git add routes/flashcards.py services/flashcard_import_service.py tests/test_flashcards_routes.py tests/test_flashcard_import_service.py
git commit -m "feat(flashcards): encrypt front/back at rest, decrypt-aware dedupe (#518)"
```

---

### Task 10: PR D — study_guides.content (#518)

**Files:**
- Modify: `backend/routes/study_guide.py` (insert ~:203; list read ~:248 `content` use; cached read ~:322; imports)
- Test: `backend/tests/test_study_guide_encryption.py` (create)

**Interfaces:**
- Consumes: `encrypt_json`, `decrypt_json_column`.
- Produces: `study_guides.content` ciphertext at write; both readers hand plaintext dicts onward.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_study_guide_encryption.py` in the FakeTable style of `test_notes_service.py` (patch `routes.study_guide.table`); cover:

```python
def test_generate_inserts_encrypted_content():
    # Patch the module's agent/generation seam per its existing tests (or call
    # _generate_and_insert with the agent mocked); assert the recorded insert's
    # content is a str and decrypt_json_column(row["content"])["exam"] matches.

def test_cached_read_decrypts_content():
    from services.encryption import encrypt_json
    # cached select returns [{"content": encrypt_json({"exam": "Midterm", ...}), ...}];
    # response "guide" must be the plaintext dict.

def test_list_decrypts_content_for_titles():
    # guides list rows carry encrypt_json content; each result entry's
    # exam_title/overview must be plaintext.

def test_reads_tolerate_legacy_plaintext_dict_rows():
    # content as a raw dict — identical responses.
```

- [ ] **Step 2: Run to verify failure, then implement**

`routes/study_guide.py` — extend the existing `services.encryption` import with `encrypt_json, decrypt_json_column`; at the insert:

```python
        "content": encrypt_json(content),
```

In `get_cached_guides`' result loop:

```python
        content = decrypt_json_column(g.get("content")) or {}
```

In the cached-read return (~:322):

```python
        return {"guide": decrypt_json_column(row["content"]), "generated_at": row["generated_at"], "cached": True}
```

(The ETag derives from `id + generated_at` only — no change.)

- [ ] **Step 3: Run, verify fail-on-revert, commit**

Run: `venv/bin/python -m pytest tests/test_study_guide_encryption.py -q` → PASS. Stash/verify-fail/pop as in Task 2.

```bash
git add routes/study_guide.py tests/test_study_guide_encryption.py
git commit -m "feat(study-guide): encrypt content JSON at rest (#518)"
```

---

### Task 11: PR D — room_summaries.summary (#518)

**Files:**
- Modify: `backend/services/social_cache_service.py` (both functions)
- Test: `backend/tests/test_social_cache_service.py` (create)

**Interfaces:**
- Consumes: `encrypt_if_present`, `decrypt_if_present`.
- Produces: `save_summary` stores ciphertext; `get_cached_summary` returns plaintext or `None`. `routes/social.py` is untouched.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_social_cache_service.py` (FakeTable pattern from `test_notes_service.py`, patching `services.social_cache_service.table`):

```python
"""#518: room_summaries.summary is ciphertext at rest; cache keys on member_hash."""
from unittest.mock import patch

from services.encryption import decrypt, encrypt
from services.social_cache_service import get_cached_summary, save_summary, _compute_hash


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.upserted = []

    def select(self, *a, **k):
        return list(self.rows)

    def upsert(self, data, on_conflict=None):
        self.upserted.append(data)
        return [data]


def test_save_summary_encrypts():
    fake = FakeTable()
    with patch("services.social_cache_service.table", return_value=fake):
        save_summary("room1", ["s1", "s2"], "Everyone is stuck on recursion")
    row = fake.upserted[0]
    assert row["summary"] != "Everyone is stuck on recursion"
    assert decrypt(row["summary"]) == "Everyone is stuck on recursion"
    assert row["member_hash"] == _compute_hash(["s1", "s2"])  # hash stays comparable


def test_get_cached_summary_decrypts_on_hash_hit():
    members = ["s1", "s2"]
    fake = FakeTable(rows=[{
        "summary": encrypt("Everyone is stuck on recursion"),
        "member_hash": _compute_hash(members),
    }])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", members) == "Everyone is stuck on recursion"


def test_get_cached_summary_tolerates_legacy_plaintext():
    members = ["s1"]
    fake = FakeTable(rows=[{"summary": "plain", "member_hash": _compute_hash(members)}])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", members) == "plain"


def test_get_cached_summary_miss_on_stale_hash():
    fake = FakeTable(rows=[{"summary": encrypt("old"), "member_hash": "stale"}])
    with patch("services.social_cache_service.table", return_value=fake):
        assert get_cached_summary("room1", ["new"]) is None
```

- [ ] **Step 2: Run to verify failure, then implement**

`services/social_cache_service.py`:

```python
from services.encryption import decrypt_if_present, encrypt_if_present
...
    if rows and rows[0]["member_hash"] == current_hash:
        return decrypt_if_present(rows[0]["summary"])
...
            "summary": encrypt_if_present(summary),
```

- [ ] **Step 3: Run, verify, commit**

Run: `venv/bin/python -m pytest tests/test_social_cache_service.py -q` → PASS.

```bash
git add services/social_cache_service.py tests/test_social_cache_service.py
git commit -m "feat(social): encrypt cached room summaries at rest (#518)"
```

---

### Task 12: PR D — backfill, seed, roundtrip, oracle, CLAUDE.md for #518's columns

**Files:**
- Modify: `backend/db/backfill_encryption.py`, `backend/db/seed_local_rich.py`, `backend/e2e_oracles/gather.py`, `backend/tests/integration/test_encryption_roundtrip.py`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything the B/C ops tasks used; seed constants `ROOM_STUDY`, `_FLASHCARDS`, `_STUDY_GUIDES`.
- Produces: `RUNNERS["flashcards"]`, `RUNNERS["study_guides"]`, `RUNNERS["room_summaries"]`; encrypted seed for flashcards/study_guides; seeded `room_summaries` row for `rich-room-study-group`.

- [ ] **Step 1: Backfill runners**

```python
def backfill_flashcards(apply: bool) -> dict:
    return _encrypt_text_column("flashcards", ["front", "back"], pk="id", apply=apply)


def backfill_study_guides(apply: bool) -> dict:
    return _encrypt_json_column("study_guides", "content", pk="id", apply=apply)


def backfill_room_summaries(apply: bool) -> dict:
    return _encrypt_text_column("room_summaries", ["summary"], pk="room_id", apply=apply)
```

Register `"flashcards"`, `"study_guides"`, `"room_summaries"` in `RUNNERS`.

- [ ] **Step 2: Seed — encrypt in place + one room_summaries row**

`seed_flashcards()`:

```python
                "front": encrypt_if_present(front),
                "back": encrypt_if_present(back),
```

`seed_study_guides()`:

```python
                "content": encrypt_json(content),
```

New seeder after `seed_study_guides` (note the `room_id` PK — `insert_if_absent` keys on `id`, so insert directly with an existence check):

```python
def seed_room_summaries() -> None:
    # #518: room_summaries.summary is 🔒. PK is room_id (no id column), so this
    # can't go through insert_if_absent.
    from db.connection import table as _table
    if not _table("room_summaries").select("room_id", filters={"room_id": f"eq.{ROOM_STUDY}"}):
        _table("room_summaries").insert({
            "room_id": ROOM_STUDY,
            "summary": encrypt_if_present("The group is reviewing recursion before the midterm."),
            "member_hash": "rich-member-hash-v1",
        })
        h.record("room_summaries", created=True)
    else:
        h.record("room_summaries", created=False)
```

(match `seed_helpers`' actual `record` signature — check `db/seed_helpers.py` when editing; if `record` is module-internal, mirror how other seeders report instead.) Call it in `main()` after `seed_study_guides()`; add `"room_summaries"` to `_SUMMARY_ORDER` after `"room_messages"`.

- [ ] **Step 3: Roundtrip entries**

`_TEXT_COLUMNS` additions:

```python
    ("flashcards.front", "flashcards", "id", "rich-fc-cs-1", "front",
     "What is a variable?"),
    ("flashcards.back", "flashcards", "id", "rich-fc-cs-1", "back",
     "A named storage location for a value."),
    ("room_summaries.summary", "room_summaries", "room_id",
     "rich-room-study-group", "summary",
     "The group is reviewing recursion before the midterm."),
```

New JSON test:

```python
def test_study_guides_content_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "study_guides", "id", "rich-guide-cs-f25-mid", "content")
    assert isinstance(raw, str), "content stored as PLAINTEXT JSONB — encryption regressed"
    decoded = decrypt_json(raw)
    assert decoded["exam"] == "Midterm Exam"
```

- [ ] **Step 4: Oracle manifest + CLAUDE.md**

Manifest: `("flashcards", "id", "front")`, `("flashcards", "id", "back")`, `("study_guides", "id", "content")`, `("room_summaries", "room_id", "summary")`.
CLAUDE.md: extend the encrypted list with `flashcards.front`/`back`, `study_guides.content`, `room_summaries.summary` (derived content, #518).

- [ ] **Step 5: Full suite + dry-run + Chapter-1 spot check**

Run: `venv/bin/python -m pytest tests/ -q` → PASS.
Run: `venv/bin/python -m db.backfill_encryption --table flashcards --table study_guides --table room_summaries` → dry-run counts.
The study-guide cache-hit journey and flashcard journeys run in the Chapter-1 lane — the PR-final e2e cycle (Task 13) is the real gate.

- [ ] **Step 6: Commit, push, open PR D**

```bash
git add db/backfill_encryption.py db/seed_local_rich.py e2e_oracles/gather.py tests/integration/test_encryption_roundtrip.py ../CLAUDE.md
git commit -m "feat(ops): backfill/seed/oracle/roundtrip coverage for derived-content encryption (#518)"
git push -u origin feat/522-d-518-derived
gh pr create --base feat/522-c-521-quiz --title "feat(derived): encrypt flashcards, study guides, room summaries (#518)" --body "Closes #518.

Derived content no longer leaks its encrypted sources:
- \`flashcards.front/back\` — both insert paths (generated + imported); dedupe decrypts before Levenshtein
- \`study_guides.content\` — encrypt_json; ETags unaffected (id+generated_at)
- \`room_summaries.summary\` — cache keys on member_hash, unaffected
- rollout-safe legacy-row reads (tested), backfill runners, encrypted seed, roundtrip tests, oracle entries

Stacked on #521's PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 13: Per-PR verification + merge + backfill sequence (the gate)

**Files:** none (execution runbook).

**Interfaces:**
- Consumes: PRs A–D open; every prior task's tests green.
- Produces: all four issues closed, staging + prod backfilled, docs synced.

- [ ] **Step 1: Full e2e cycle on the stack tip (branch D)**

One flock invocation wrapping the WHOLE cycle, from repo root:

```bash
flock /tmp/claude-1000/sapling-e2e-stack.lock bash -c '
  set -e
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  make e2e-up
  (cd frontend && npx playwright test)
  (cd backend && venv/bin/python -m e2e_oracles)
  status=$?
  make e2e-down
  exit $status
'
```

Expected: journeys green; oracles exit 0 — the ciphertext oracle now proves all 13 new columns encrypted at rest in a really-running stack. Testing the tip covers B and C's changes too; if the tip needs a fix, re-run after fixing.
Before any run, clear stale artifacts that poison review: `rm -rf frontend/test-results frontend/e2e/results` (check `argv` in last-run.json if results look wrong).

- [ ] **Step 2: `/code-review` each PR, in order A → B → C → D**

Fix findings on the PR's own branch; `git rebase` the children after any base amend (`git checkout feat/522-b-520-feedback && git rebase feat/522-a-519-newsletter-adr`, and so on up the stack; force-push rebased branches with `--force-with-lease`).

- [ ] **Step 3: Merge A; retarget + merge B; backfill #520**

```bash
gh pr merge <A> --squash --delete-branch        # docs only
# B auto-retargets to main when A's branch deletes; verify: gh pr view <B> --json baseRefName
gh pr merge <B> --squash --delete-branch
cd backend
dotenv -f .env.staging run -- python -m db.backfill_encryption --table feedback --table issue_reports          # dry run, read counts
dotenv -f .env.staging run -- python -m db.backfill_encryption --apply --table feedback --table issue_reports
dotenv -f .env.production run -- python -m db.backfill_encryption --apply --table feedback --table issue_reports
```

(If a merge 502s while the PR shows OPEN: check state, retry until MERGED — known gh wedge.)

- [ ] **Step 4: Merge C; backfill #521**

```bash
gh pr merge <C> --squash --delete-branch
cd backend
dotenv -f .env.staging run -- python -m db.backfill_encryption --apply --table quiz_attempts --table quiz_context
dotenv -f .env.production run -- python -m db.backfill_encryption --apply --table quiz_attempts --table quiz_context
```

- [ ] **Step 5: Merge D; backfill #518**

```bash
gh pr merge <D> --squash --delete-branch
cd backend
dotenv -f .env.staging run -- python -m db.backfill_encryption --apply --table flashcards --table study_guides --table room_summaries
dotenv -f .env.production run -- python -m db.backfill_encryption --apply --table flashcards --table study_guides --table room_summaries
```

Always dry-run first against each env and read the counts before `--apply`.

- [ ] **Step 6: Close out the epic**

- Verify #518/#519/#520/#521 auto-closed; comment on #522 with the per-child outcome (`#484` deliberately still open, ADR 0025).
- Stage ONE Canopy `sapling-infrastructure` doc update: the encrypted-columns table gains the 11 new columns + the newsletter exception (re-base on the doc's current version — it had a v3 staged change; read before writing).
- Record the session (user runs `/record-session`; `update-plan` is user-invoked too if the roadmap should note the epic).

## Self-Review

**Spec coverage:** #519 → Task 1; #520 → Tasks 2–5; #521 → Tasks 6–8; #518 → Tasks 9–12; cross-cutting table → Tasks 5/8/12 (same five artifacts each); rollout-safety invariant → legacy-row tests in Tasks 3/7/9/10/11 + graceful helpers; ops/backfill + Canopy + epic DoD → Task 13. Wireframe surface → Task 4.

**Type consistency:** `decrypt_json_column(value: Any) -> Any` defined in Task 6, consumed with that exact name in Tasks 7, 10 (Task 12's roundtrip tests use `decrypt_json` directly on raw DB strings — correct, the guard is for PostgREST reads). Admin response shapes in Task 3 match Task 4's TS types field-for-field (`feedback`/`reports` keys, `user_name` addition). Backfill runner names match their `RUNNERS` keys and the Task 13 `--table` arguments. Seed ids (`rich-fb-1`, `rich-issue-1`, `rich-qc-cs-variables`, `rich-fc-cs-1`, `rich-guide-cs-f25-mid`, `rich-room-study-group`) are used verbatim in the roundtrip entries.

**Known judgment calls left to the implementer, deliberately:** Tasks 7/9/10 test sketches say "arrange as the module's existing tests do" — those modules' fixtures are the authority on mock wiring; the assertions to make are fully specified. Task 12's `seed_room_summaries` must match `seed_helpers.record`'s real signature at write time.
