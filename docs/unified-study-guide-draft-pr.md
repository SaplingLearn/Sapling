## Summary

Unify assessment preparation under Study Guide, replacing separate plan/guide
creation flows. Students enter a quiz/exam date manually and optionally link
undated assignments or library documents. One bounded AI generation supplies:

```text
Assessment + selected materials
  -> guide overview and topic study points
  -> topic checklist with live concept mastery
  -> daily schedule before the assessment
```

Topics, availability and sessions are editable. Session completion records activity
without raising mastery. Earlier saved guides remain read-only history. Plans use
encrypted payloads, enrollment ownership checks and versioned updates. Includes
sidebar client-script and safe schema-error handling fixes found during local testing.

## Evidence

- **Before:** separate assessment-guide and plan flows; creation relied on dated exams.
  **After:** unified-flow tests cover manual dates, undated materials, guide content,
  saved history and preserving study points during topic edits.
- Frontend: 1,791 tests passed, 2 skipped; typecheck and production build passed.
  Lint passed with 19 existing warnings.
- Backend: 248 selected regression tests passed; feature lint passed. Covers access
  control, encrypted state, schedule constraints, stale updates, AI budgets and
  unsupported-evidence retries without paid model calls.
- Memory-only browser preview verified guide content, scheduling, completion/reload
  and no external requests. Real-storage integration and full-app E2E are unrun.

## Merge Danger

**Door:** two-way

Code is reversible; the new table is additive. Do not drop it during rollback if
students have created plans. Apply the migration using the normal reviewed deployment
workflow. No hosted migrations/data changes or environment edits were made locally.

**Blast Radius:** Study

A read-only check found 34 pending migrations on the locally configured live Supabase
project, including required plan, mastery and flashcard schema. Database integration
must be verified before promoting this draft to a deployment. Build success does not
verify that environment. PR #728 is the UI baseline; initially target its branch
`feat/redesign-integration`, then retarget after it merges.
