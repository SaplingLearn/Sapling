# 0036 — Durable tutor-turn interruption timing and completion fencing

Date: 2026-10-19
Status: Accepted for PR #673; verification and release gates remain in force.

## Context

Failed tutor turns kept their independent-time anchor only in worker memory.
A restart could discard it and allow a teach-phase claim to use time since an
older successful reply. A late reply could also complete after a newer request
had started. ADR0024's failure contract protects transcript and learning writes;
it does not provide durable operational timing for a materialised session.

## Decision

- Before planning or dispatching a materialised tutor turn, acknowledge an
  open-session compare-and-set of prose-free `turn_activity`: random operation
  ID, pending status and timestamp. A missing/closed session or failed write
  prevents model dispatch. This metadata grants no evidence or mastery.
- A pending or malformed activity is not independent study time. After a
  worker crash, another worker reads that durable marker and conservatively
  declines a teach-attempt ceiling increase. Legacy documents without activity
  retain their existing served-time behavior.
- A subsequent request may supersede an interrupted/pending operation. Only
  the current pending operation can complete; its activity completion, normal
  served-time update and feedback bookkeeping share the existing session CAS.
  A superseded or duplicate completion fails before applying those changes.
  An older cancellation cannot overwrite the newer operation's metadata.
- A failed or paused turn persists interruption time without changing goals,
  transcript, verdicts, learner state or evidence. If its final timing write
  fails, the previously acknowledged pending record remains conservative after
  restart. A bounded worker cache is only an additional conservative fallback.
  Cancellation-path writes run off the event loop under the existing shielding
  pattern. Never replace the original failure with a timing-write error.
- The legacy lazy opener still has no session row until materialisation and
  earns no teach-attempt credit. This change does not claim durable storage of
  an unmaterialised opener. It does not add a request queue or guarantee that
  cancellation stops provider billing.

## Consequences and verification limits

Failure now changes operational session metadata; it still cannot fabricate
learning progress or mark failed feedback as delivered. A new request fences
older state completion rather than silently granting a second completion.

The transcript write, evidence journal, learner scalar and graph mirror are
still separate operations. This decision does not claim a multi-table evidence
transaction, crash-safe completion of every grading side effect, or a global
model-spend reservation. Those remain separate engineering work.

Verification must cover cold-worker interrupted/pending records, cancellation,
stale completion/cancellation, closed/missing sessions, failed admission before
AI dispatch and unchanged learning records, followed by the final-source real
database and browser lanes. No production promotion is authorized here.
