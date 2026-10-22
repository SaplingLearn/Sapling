# 0030: Swap the agents' LLM provider from Gemini to Anthropic Claude

- Status: proposed
- Date: 2026-10-22
- Supersedes: none (amends ADR 0001's "Model selection stays Gemini-only")

## Context

Every LLM call already runs through one seam — Pydantic AI agents built by
`agents/_providers.py::model_for` (ADR 0008 per-task slots, ADR 0019 function
mode, ADR 0024 no other seam) — but that seam hard-coded Google: `model_for`
always built a `GoogleModel`, slot defaults were `gemini-*` names, Gemini-only
settings (`google_thinking_config`, `temperature`) lived on individual agents,
the hermetic test guard cut only the google-genai transport, the cost table
priced only Gemini, and every `llm_usage` row was labelled `provider='gemini'`.
We are moving the agents to Anthropic's Claude. Two facts shape how: the
pinned pydantic-ai 1.x line (capped `<2` over the `run_stream_events` change)
predates Claude 5.x, so for `claude-haiku-5-5`/`claude-sonnet-5-5` it would
send a forced `tool_choice: any` for every structured output (a 400 on Sonnet
5.5, refused alongside Haiku 5.5's default thinking), forward `temperature`
(rejected by Claude 4.7+), and never use native JSON output; and Anthropic has
no embeddings API, while RAG stores 768-d `gemini-embedding-001` vectors in
`VECTOR(768)` columns.

## Decision

The provider is inferred from the slot's model name — `claude-*` → Anthropic,
`gemini-*` → Google, anything else raises — so `SAPLING_MODEL_<TASK>` can move
one slot back to Gemini with no code change. Every slot defaults to Claude:
Claude Haiku 5.5 for all former Flash and Flash-Lite slots (it lists at
$0.10/$0.50 per MTok against Flash-Lite's $0.10/$0.40 and Flash's $0.30/$2.50,
which keeps the no-price-increase rule) with per-task `effort` (`low` where
Flash-Lite ran without thinking — quiz included — and `medium` where Flash
thought), and Claude Sonnet 5.5 at `effort=low` for the tutor (the role Pro
held). Prompt caching is on for the tool-loop slots (tutor, quiz, note chat). We
stay on pydantic-ai 1.107 and supply the Claude 5.x facts ourselves in
`_anthropic_profile` (native constrained-JSON output by default, no forced
tool choice, no sampling settings, adaptive thinking + effort), resolving the
output mode before `AnthropicModel.prepare_request` so the native schema goes
out strict; the per-event-loop provider fix (#354/#436) becomes
`_LoopSafeProviderMixin`, shared by both providers. RAG embeddings stay on
Gemini. Free-prose length caps (`max_length` on headlines, abstracts,
rationales, descriptions) get a word-boundary clip (`agents/_bounded.py`)
because Claude's strict JSON mode cannot enforce `maxLength` at decode time;
identifier-like fields stay strict.

## Consequences

- Positive: one seam, two providers. Any slot can be rolled back to Gemini by
  env, and `tests/test_anthropic_provider.py` pins provider inference, the
  5.x profile, per-task settings and the exact request sent to the SDK.
- Positive: the live eval re-recording kept or raised output volume on every
  dataset (summaries, quiz explanations, tutor replies), kept syllabus
  weights verbatim, kept quiz generation at 1.0 on every evaluator, and the
  tutor now searches the student's course materials on nearly every turn
  (Gemini did so on 5 of 16 eval turns, Claude on 13).
- Cost, measured live on the eval datasets (2026-10-22, same inputs both
  sides): the full mix fell from $0.389 (Gemini) to ~$0.20 (Claude). By slot:
  concepts −90%, syllabus −88% (Flash → Haiku); tutor deep turns −41%
  (Pro → Sonnet at `effort=low`, cached). The former Flash-Lite slots did
  NOT hold the no-price-increase rule: quiz +19%, classifier +83%, summary
  +133%, fast-tier tutor +43% — Haiku 5.5 is the cheapest Claude model, its
  tokenizer counts more tokens than Gemini's, and its output rate is $0.50
  vs $0.40. Disabling thinking did not close the gap and cost quality (quiz
  question count/coverage, classifier shareability), so it was rejected.
  Quiz was ~88% of production spend in the last snapshot, so production
  spend is expected to rise modestly until the doc-pipeline/tutor savings
  dominate; `llm_usage` (now provider-labelled and cache-aware) is the
  authority to watch.
- Positive: the swap surfaced and fixed a provider-independent bug — the
  streamed tutor persisted only the FINAL model response's text, so a turn
  that explained, called a tool, then added a line lost the explanation from
  the transcript. Both tutor paths now persist every text part of the turn,
  joined by `chat_stream.join_text_parts`.
- Negative: `GEMINI_API_KEY` stays required (embeddings), and
  `ANTHROPIC_API_KEY` is now required at startup — every deployed environment
  (Railway staging + production) needs it set BEFORE this merges, or boot
  fails closed (#174). A leftover `SAPLING_MODEL_<TASK>=gemini-*` in a deployed
  env silently keeps that slot on Gemini.
- Negative: the hand-written 5.x profile is ours to maintain until a
  pydantic-ai 2.x upgrade (which knows these models) lands with the
  `chat_stream.py` migration; `test_every_default_slot_is_claude` and the
  effort-coverage assertion fail any new slot added with a Gemini default or
  without an effort level.
- Negative: Claude follows the tutor prompt's mastery rule literally — it
  updates mastery only when the student demonstrated understanding or a
  misconception, where Gemini also bumped mastery (+0.05 to +0.25) on a bare
  "explain X" request. The eval's `MasteryUpdateEmitted` baseline drops for
  the expository cases. Whether "explaining" should move mastery is a
  product decision; the prompt was deliberately not changed to replicate it.
- Negative: Anthropic is a new processor of student content; the privacy
  policy, terms and in-app AI disclaimer now name it, and the data-handling
  review ADR 0027 asked for before Jev applies here too.
- Neutral: the `/api/gemini-test` route, the `GEMINI_VISION_OCR_*` env vars,
  the `services/extraction_backends/gemini_vision_backend.py` module and the
  decision seam's `flash_lite` backend name keep their pre-swap names to
  avoid breaking deployed config and flags; they now drive Claude.
- Neutral: prompt caching is enabled only on the tool-loop slots;
  `services/llm_pricing.py` prices cache reads at 0.1x and 5-minute writes at
  1.25x of input (Claude only — Gemini's implicit-cache discount stays
  unmodelled, as before).
- Neutral: Claude's strict JSON mode cannot enforce `maxLength` etc. at
  decode time; prose caps are clipped locally (`agents/_bounded.py`) and an
  ordering callers depend on is imposed in a validator.
