# 0020 — Interrupted tutor turns keep the partial reply and offer Retry (#356 item 5)

**Status:** implemented (on `main`, with PR #349 merged — ChatPanel `interrupted`/Retry + Learn re-dispatch; journey: `frontend/e2e/streaming.spec.ts`) · **Issue:** #356 (PR #349 e2e-smoke item 5) · **Implements:** the streaming feature in PR #349

## The decision

When a streaming tutor turn is **stopped by the user** or **fails mid-stream**
(a Rung-2 `error` event, including during a Rung-3 JSON fallback), the client
**keeps the partial reply text visible, marks the bubble interrupted, and offers
Retry**. Because nothing is persisted until a turn completes, Retry simply
re-sends the same turn. This is the behavior the streaming spec already
specifies — we adopt it rather than amend the spec.

## Context

PR #349 shipped the SSE streaming tutor with a known divergence from spec,
called out in its "Known gaps":

> **Stop/Rung-2 discards the partial reply and offers no Retry.** As shipped,
> Stop appends nothing (leaving the user's message with no reply) and Rung 2
> shows a generic error.

The e2e-smoke item 5 (#356) asked us to confirm this live and decide:
**(a)** implement per spec — keep the partial, mark it interrupted, offer Retry;
or **(b)** amend the spec to bless the discard.

The spec (`docs/superpowers/specs/2026-07-16-streaming-design.md`) is explicit:

- Bubble-state table (§ "failed / stopped"): *"mid-stream `error` or user Stop:
  keep the partial text visually, mark it interrupted, offer Retry (nothing was
  persisted, so Retry re-sends the turn)."*
- Failure ladder: *"persist nothing; client marks the bubble interrupted and
  offers Retry. No silent auto-retry."*

## Why (a), not (b)

- **No dropped turns.** Discarding on Stop leaves the user's own message sitting
  with no reply and no affordance to recover — the worst outcome of the two,
  and precisely what a "Stop" (pause, not delete) does not imply.
- **The partial is real output.** Tokens already rendered are the model's actual
  answer so far; keeping them visible (dimmed/"interrupted") is more useful than
  blanking the bubble.
- **Retry is already safe.** The persistence contract persists exactly once, on
  completion, before `done` — so a stopped/failed turn wrote nothing to the
  TRANSCRIPT, and Retry re-sends without risk of a double-write or a phantom
  half-message. *(Amended by #151a: since the tutor gained in-band graph/mastery
  TOOLS, a failed turn may have real tool writes — the server marks such
  errors `retryable: false` and the client ladder honors it (no automatic
  re-run; the interrupted+Retry treatment lets the STUDENT decide), and 413s
  are likewise never auto-retried. The transcript half of this argument is
  unchanged. ADR 0024 records the full server+client rung ladder as the
  canonical description post-#151.)* (`CancelledError`
  is deliberately not caught; a mid-stream disconnect cancels the generator
  before persistence — covered by `backend/tests/test_chat_stream.py`.)
- **Consistency across rungs.** The same interrupted+Retry affordance covers a
  user Stop, a Rung-2 mid-stream error, and a failure during the Rung-3 JSON
  fallback, so degraded states never look "frozen."

## Scope / where it lands

Recorded while the streaming chat UI (`frontend/src/components/ChatPanel.tsx`,
`frontend/src/components/screens/Learn.tsx`, `frontend/src/lib/api.ts`) still
lived on the PR #349 branch (`feat/streaming-tutor`); the decision deliberately
preceded the implementation. #349 has since merged, and the implementation
landed on `main` as the ADR-0020 half of the #164/#356 PR: ChatPanel's
`interrupted`/Retry treatment, Learn's ladder rework (Stop / Rung-2 / failed
Rung-3 all keep the partial and offer Retry, with a session-switch guard so a
late turn never writes into another session's transcript), and the
`frontend/e2e/streaming.spec.ts` journeys pinning it. Acceptance for item 5 in
#356 — decision recorded and implemented — is met.

## Consequences

- ChatPanel gains an `interrupted` bubble treatment (keep `streamingText`, style
  as interrupted) and a Retry action; Learn wires Retry to re-dispatch the
  turn's original `message`/`mode`.
- Scope note (implementation): this covers chat TURNS (`send`'s ladder — Stop,
  Rung-2, and a failed Rung-3 fallback all get the interrupted+Retry bubble).
  A stopped/failed session GREETING (`beginSession`) has no transcript turn to
  mark: no user message exists yet and nothing was persisted, so it returns to
  the entry screen with the topic draft intact — Start is its retry affordance.
- No backend change: the persistence contract and fallback ladder already
  guarantee "nothing persisted on stop/failure," which is what makes Retry a
  plain re-send. This is a client-rendering decision on top of the existing seam.
