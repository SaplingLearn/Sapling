## Summary
Unify assessment study guides, topic checklists, and daily study planning.

## Description
Students enter a quiz/exam date and attach relevant Library files or assignments.
Sapling generates topic study points, an interactive checklist, and recommended
focus topics and study time for each day leading up to the assessment.

## Changes Made
- Show all enrolled courses as active, without semester selection or filtering
  in the study guide. Existing enrollment ownership and storage are preserved.
- Combine guide content, topic checkboxes, daily focus and progress in one workspace.
- Explicitly support Library study guides, assignment files, notes, slides and readings.
- Allow manual assessment dates and undated materials.
- Recommend daily study time automatically; remove time-entry fields.
- Support editing topics, completing sessions, rescheduling and replanning.
- Keep checklist/session completion separate from concept mastery.
- Fix misleading creation-conflict errors and stale new-assessment form values.
- Use Anthropic with native token counting, bounded usage and protected receipts.
- Preserve saved-guide history and add a no-key local-storage smoke test.

## Related Issues
None linked.

## Testing
- [x] Tested locally against real Supabase storage
- [x] Added/updated tests
- [x] Previous full frontend suite: 1,792 passed, 2 skipped
- [x] Final course-selection change: 18 targeted frontend tests passed
- [x] 353 selected backend tests passed
- [x] Typecheck, lint and production build passed
- [x] No-key browser flow and encrypted local-storage checks passed
- [x] Anthropic SDK tested using an in-process HTTP mock
- [x] Anthropic receipt settlement/replay tested in a rolled-back local transaction
- [ ] Live Anthropic generation: backend key unavailable locally

## Screenshots (if applicable)
To be added.

## Notes for Reviewers
- Stack this draft on `feat/redesign-integration` while PR #728 remains open;
  retarget to main after that dependency merges.
- No hosted database changes or environment-file edits were made. Migrations
  were applied only to the verified local database, without a reset.
- Deployment requires the assessment-plan migration and the append-only Anthropic
  receipt compatibility migration through the normal reviewed promotion workflow.
- Run from backend/ without a model key:
  `.\venv\Scripts\python.exe -X utf8 -m scripts.smoke_assessment_guide`.
- Local env files and the unrelated .agents skill edit are excluded.
