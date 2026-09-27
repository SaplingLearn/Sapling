# 0027: Typed decision seam, Jev as a backend, and an observe-only tutor router

- Status: accepted
- Date: 2026-09-26
- Relates to: #640 (seam + tutor router), #642 (Jev backend), #641 (upload
  decisions and reranking, the next caller), #643 (AI-redesign tracker);
  ADR 0008 (per-task model slots), ADR 0019 (function-mode seam), ADR 0024
  (Pydantic AI is the only LLM seam)
- Supersedes: none
- Numbering: 0026 is taken on `main` (newsletter plaintext). Open PR #512 also
  claims 0026 and must renumber when it rebases; it should take 0028.

## Context

Several hot-path choices are either missing or made by a generating LLM as a
side effect of generating: does this tutor turn need retrieval, does the query
need a history-aware rewrite (#633), which model tier does it need, is it a
request for graded work, is it an injection attempt. The upload pipeline has
the same shape (#641: shareability, reranking). Each of these is a *small
typed judgment with a confidence*, not generation, and asking a chat model for
it in prose makes it slow, costly and hard to measure.

TypeSafe's **Jev** is a model built for exactly this: send a `state` and typed
questions (`noul` = yes/no with P(yes), `choice` with per-option
probabilities, `score` over ordered levels), get calibrated answers back in
well under a second at $0.042 per 1M input tokens with free output. It is also
a brand-new vendor.

The #640 premise correction matters here: tutor turns do not all go to Pro.
The UI's `fast`/`smart` toggle always sends a pref, so model choice is a
sticky user setting rather than a per-turn decision. Whether a router should
become the default selector (a new `auto` pref) or escalate/de-escalate the
toggle is an open product question.

## Decision

1. **One seam: `backend/services/decisions.py`.** Typed questions in
   (`YesNo` / `Choice` / `Score`, each with a safe `default`), typed `Answer`s
   out, each with a confidence in [0, 1] normalised to TypeSafe's convention
   (0 = no idea, 1 = certain; for yes/no, `|2·P(yes) − 1|`). Callers never
   know which backend answered.

2. **Backends chosen by env, default `off`.** `SAPLING_DECISIONS_BACKEND` is
   `off | flash_lite | jev`, and the **code default is `off`**, so merging
   this changes no production behaviour and no cost until an operator opts
   in.
   - `flash_lite`: a Pydantic AI agent (`agents/decision.py`) on a new
     `decision` slot in `agents/_providers.py` (default
     `gemini-2.5-flash-lite`, overridable via `SAPLING_MODEL_DECISION`), so it
     stays inside ADR 0024's single LLM seam and ADR 0008's routing. Its
     output schema is generic (`answers: [{key, value, confidence}]`), which
     fits the #153 schema budget once for every caller; the seam validates
     each value against its question.
   - `jev`: a thin async client (`services/typesafe_client.py`) for
     `POST https://api.typesafe.ai/v1/systemone` with a Bearer
     `TYPESAFE_API_KEY`. It is bespoke rather than the official `typesafe-sdk`
     (0.7.2, pre-1.0, days old) because the call is one POST, and the SDK's
     main feature, automatic 429/529 backoff, is the wrong behaviour on a
     latency budget with a fallback available. The env names match the SDK's,
     so switching later costs no reconfiguration. The default model is the
     pinned `jev-1.13.0`, not the `jev-latest` alias, as the vendor advises
     once thresholds are tuned.
   - `function`: automatic under `SAPLING_MODEL_MODE=function` unless the
     backend is explicitly `off`. It is the same agent on the FunctionModel,
     answered by the `decision` handler in `agents/function_handlers_e2e.py`
     (and `function_handlers_showcase.py`). ADR 0019 unchanged: Jev is never
     dialled from the deterministic lane. `function` may also be set
     explicitly (backend or shadow); outside function mode it resolves to
     `off` with a one-time warning, never to a live model.

3. **Degradation, never failure.** Jev degrades to `flash_lite` on a missing
   key (without a network call), a timeout (`SAPLING_DECISIONS_JEV_TIMEOUT_MS`,
   default 1.5 s, enforced as a wall-clock deadline), any HTTP or transport
   error, or a malformed body. A state that cannot fit the 32k
   state-plus-longest-question budget is first trimmed (the oldest items of
   caller-named list fields such as a conversation tail; the text being
   judged is never clipped); if it still cannot fit, it goes to `flash_lite`
   only when the prompt also fits the decision agent's `WORKER_LIMITS`
   (estimated prompt plus output reserve, times the request limit, since
   each validation retry re-sends it) and otherwise straight to safe
   defaults (`jev_state_over_budget`) — at today's limits, always the
   latter. If `flash_lite` fails, every key gets its safe default. Per key, an answer below
   `SAPLING_DECISIONS_CONFIDENCE_FLOOR` (default 0.5, TypeSafe's own
   suggestion) or outside the allowed set also falls to its default. Answers
   match the allowed keys trimmed and case-insensitively; an off-list answer
   keeps what the backend said and its confidence on the `Answer`
   (`default_reason="invalid"`). A Jev 200 with no readable key degrades like
   any other Jev failure (`jev_bad_answers`), as does an unexpected exception
   in the Jev path. `decide()` never raises.

4. **Observable by construction.** Each call emits one `decision.made` event
   (registered in `EVENT_TAXONOMY`, category `usage`) with backend, requested
   backend, fallback reason, model, latency, and per key the applied value,
   **raw** value and confidence. The event carries no state text. The same
   fields go to a Logfire log. An off-list answer shows as `raw: "<invalid>"`
   on the event (free model text could echo the student). Token usage goes to
   `llm_usage` under the caller's `request_id` (explicit, since the router
   runs outside the request contextvar), with `provider="typesafe"` for Jev,
   priced in `services/llm_pricing.py` (input only). `llm_usage.cost_usd` is
   NUMERIC(18,10) (migration `20260927220057`, consolidated with the PostHog opt-out column and shipped in #677): a Jev token is $0.000000042,
   and the old 6dp column rounded decision-sized costs (a sub-12-token call
   to $0). Any served `jev-*` id without an exact price entry is priced at
   the family rate, so a vendor version bump never NULL-costs a call.

5. **Shadow mode for the #642 acceptance.** `SAPLING_DECISIONS_SHADOW` runs a
   second backend concurrently and records its answers plus per-key agreement
   on the same event. The shadow never falls back and never feeds the answer —
   except that when a Jev primary degrades to flash_lite and the shadow IS
   flash_lite, the shadow's in-flight answer serves as the fallback (one
   Gemini call, not two) and the shadow is logged `shadow_same_as_served`
   with `agree: null`, never a self-comparison. An off-list answer on
   either side counts as disagreement, not unknown.
   Switching Jev on after the agreement review is one env var.

6. **Tutor router, observe-only.** `services/tutor_router.py` asks five
   questions per student chat turn (`needs_retrieval`, `needs_rewrite`,
   `complexity` easy/medium/hard, `is_graded_work_request`,
   `injection_attempt`). It is scheduled fire-and-forget from the per-turn
   PERSIST point of `/chat` and `/chat/stream` (where the student message is
   saved and `chat.message_sent` emits), so there is exactly one decision per
   persisted student turn — a stream that fails before persisting and is
   retried through `/chat` is routed once. It has its own timeout backstop.
   **Nothing acts on the answers**: retrieval, model choice and prompt are
   exactly as before. The model the turn actually ran on rides on the event
   (`model_tier` fast/smart/default — `default` whenever the pref is not
   honoured, e.g. any non-real mode — `tutor_model`, plus the raw
   `model_pref_requested`) so both answers to the #640 model-selection
   question can be costed from the same data. That question is **deliberately left open** here.
   Session openers and hint/confused/skip actions are not routed, because
   their prompts are synthetic.

## Consequences

- (+) Every future typed decision (#633, #641, the router acting) has one
  place to go, with fallback, confidence floors, cost accounting and an
  accuracy dataset built in.
- (+) Default-off plus observe-only means this lands with zero behaviour or
  cost change in production; turning the router on adds one cheap call per
  chat turn and no latency.
- (+) The function-mode backend makes the E2E lane exercise the seam on every
  tutor turn, deterministically.
- (−) **Vendor risk (Jev).** TypeSafe is a new company. There is no self-hosted
  option, so an outage, pricing change or shutdown is out of our hands, and
  the published price may be launch-subsidised. Rate limits are documented as
  "adjusting dynamically". Mitigations: Jev is never the only path (the
  fallback is automatic and per call), the key's absence is a clean
  degradation, the seam's interface is vendor-neutral, and cost is recorded
  per call so a price change shows up in rollups rather than on an invoice.
  Data handling: student messages would go to a third party. The docs say
  Jev does not train on customer requests (zero data retention is an
  enterprise option). Review this before enabling `jev` in production.
- (−) The Jev client was built from the public docs (docs.typesafe.ai/api,
  /models, /confidence, /sdk/python constants) without a live call, because no
  key existed yet. The tests replay recorded-shape payloads. The first staging
  run with a key is the real schema check.
- (−) The flash-lite backend's confidences are self-reported, not calibrated.
  They are comparable in shape to Jev's but not in meaning, which is part of
  what the shadow comparison is for.
- (−) Token estimation for the 32k budget is a pessimistic ~3 chars/token
  heuristic (Jev's tokenizer is unpublished), so near-limit states may degrade
  early. The tutor router's state is clipped far below the limit.
- Follow-ups: a labelled routing eval of at least 100 turns reporting accuracy
  per field (#640 AC); a shadow-mode agreement report (#642 AC); and then the
  model-selection decision, as its own ADR, before the router acts on
  anything.
