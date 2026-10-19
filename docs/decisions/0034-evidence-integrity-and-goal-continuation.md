# 0034 — Evidence integrity and bounded goal continuation

Date: 2026-10-18
Status: Accepted for PR #673; production launch gates remain unchanged.

## Context

ADR 0033 introduced goal-scoped diagnosis and planning. Further checks found that
repeated or malformed observations could appear independent, incomplete grader
fields could become student failures, and an approved plan could outlive a change
to its goal graph or prerequisite readiness. Finishing the first ready frontier
could also end a session plan before reaching the requested target, while an old
diagnostic miss could remain a planning block after later independent success.

A real grader run used roughly 56,000 tokens despite a 20,000-token run limit:
the usage limit was checked after the provider response. A post-response usage
check alone cannot bound generation. In the UI, a late hint response could belong
to a previous item or session, and retrying failed hint text could request another
already-earned help rung.

## Decision

- Derive diagnostic boundaries and planning evidence from distinct, validated
  independent observations. Validate outcome types, difficulty, channel and help
  provenance; reject assisted, previously seen, release-recheck, refusal,
  unavailable and malformed records. Deduplicate question hashes by first
  exposure across history, including earlier exposures that were not independent.
  Preserve raw presentation/history counts for finite fatigue limits. Unknown
  provenance is not proof of independence.
- Require complete grader verdict and support fields for the requested rubric
  labels. Missing, duplicated, invented or unreadable entries are model failures,
  not evidence that the learner failed. After the existing bounded validation
  retry, return unavailable and record no learner outcome. Keep the existing
  answer, support-span, refusal and help-floor safeguards.
- Add a provider generation cap of 4,096 output tokens and a 30-second grader
  request timeout, alongside existing run, budget and usage limits. These are
  engineering bounds; they do not establish grading accuracy or eliminate every
  provider failure. Continue to account for actual billed usage.
- Re-read the owned course graph, goal closure and prerequisite readiness before
  goal-plan approval. Reject stale scope or newly unready choices rather than
  approving the old proposal. Version goal writes and atomically require an open,
  non-closing session for goal-plan mutations. Goal edits remain limited to the
  existing pre-teaching window; preserve history and fatigue across those edits.
- Continue an explicit goal through bounded frontiers. Once the current approved
  frontier is exhausted, compute eligible, unattempted concepts in the current
  goal closure and return to planning only when another frontier is available.
  Require a new learner approval before teaching it. Retain per-session,
  per-concept, bank and budget limits; never auto-pass prerequisites or repeat an
  exhausted frontier indefinitely.
- Distinguish attempted concepts from concepts actually checked, and distinguish
  a finished session plan from proficiency or mastery. An empty bank is not a
  successful check. Keep unresolved prerequisites and remaining targets visible.
  A later distinct independent correct answer at the same or higher difficulty
  can clear an earlier miss for local planning priority; easier, assisted or
  recheck answers cannot. This does not manufacture posterior or graph evidence.
- Give asynchronous hint requests ownership of their session, item and request
  generation. Ignore obsolete responses after navigation, submission or close.
  When a rung was already granted but its text failed, retry the text action
  without granting another rung or repeating the effort request.
- Expose the existing delayed retention-check endpoints through an explicit
  Study entry. The server remains authoritative for the two-day minimum since
  evidence, unseen-item eligibility, committed poses and help/intervening-practice
  credit. Opening or completing the UI does not establish retention or mastery.

## Consequences and validation limits

Regression coverage checks evidence rejection, stale goal approval, prerequisite
chains, bounded continuation, request ownership and retention-entry behavior.
Each additional goal frontier needs fresh approval, including after resume; a
blocked or item-starved goal reports remaining work instead of success.

The finite difficulty scale and its cut-points are engineering heuristics. An
arbitrary goal can span more concepts than the three diagnostic strands assessed
in one session, so untested and unresolved scope must remain explicit. Course
prerequisites used for the real-course pilot were manually reviewed; this does
not validate automatic prerequisite discovery. Generated question rubrics have
not been expert-verified, and faulty items can still require quarantine.

Four real-model gold cases passed. That is a narrow smoke check, not grading
calibration, a representative accuracy estimate, or evidence of retention,
transfer or learning efficacy. Full verification and release review are separate
from this decision. No production promotion is authorized.
