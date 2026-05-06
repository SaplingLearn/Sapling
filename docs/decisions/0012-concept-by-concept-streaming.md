# 0012: Concept-by-concept streaming (deferred design)

- Status: proposed (deferred — design only, no implementation)
- Date: 2026-05-04
- Supersedes: none

## Context

The streaming `/upload` route currently emits a single `progress:extracted` event after `concept_extraction_agent.run()` returns the entire `ConceptList` at once. From the user's perspective, after `progress:classified` there's a 4–8s gap with no visible progress until "Extracted N concept(s)." appears.

Pydantic AI's `agent.run_stream()` exposes the model's progress toward the structured output incrementally — for a list-typed output, you can observe partial lists as the model emits them. We could push individual concepts into the SSE stream as they materialize, turning a 4s blank into a steady stream of chips appearing in the upload UI.

## Proposed design (not implemented)

```python
# In the streaming /upload route:
concept_names: list[str] = []
async with concept_extraction_agent.run_stream(
    extracted_text, deps=deps, usage_limits=WORKER_LIMITS,
) as run:
    async for partial in run.stream_output(debounce_by=None):
        # `partial` is a ConceptList with partially-populated concepts.
        new_names = [c.name for c in partial.concepts if c.name not in concept_names]
        for name in new_names:
            concept_names.append(name)
            yield sapling_event_to_sse(SaplingEvent(
                type="progress", step="concept",
                message=f"Extracted: {name}",
                data={"name": name},
            ))
```

Frontend consumes the new `progress:concept` events and renders chips one at a time in `DocumentUploadModal`.

## Why this is deferred, not built

- Concept extraction currently runs *in parallel* with summary (and syllabus, when applicable) via `asyncio.gather`. Streaming it requires either:
  - Dropping it out of the gather and running serially (loses parallelism — bad), or
  - Running gather with one streaming branch and two non-streaming, then awaiting the streaming branch's events while the others complete in the background. Doable but adds complexity to `_run_workers`.
- Pydantic AI's `run_stream` for structured outputs has model-dependent behavior. Gemini may not emit incremental list output the same way Anthropic or OpenAI models do. Need to verify empirically before we commit to a UX that depends on it.
- The current "show all 12 chips at once" UX is fine. The 4–8s gap is real but not bad-feeling — the upload modal still has the live progress label updating from other steps. Streaming concepts is a polish move, not a load-bearing fix.
- Concept ordering matters for the user-facing chips (the schema requires "ordered by importance descending"). If the model emits unimportant concepts first and the important ones last, streaming makes the UI worse, not better. Need eval data.

## When to revisit

- If user feedback says the upload feels slow after `progress:classified`. The progress label updates but says nothing about extraction internals.
- After we have eval data (now possible via `tests/evals/concept_extraction.py` per ADR 0008) showing whether Gemini emits concepts in importance order or in document-discovery order. If the latter, streaming is harmful and we should not ship it.
- If we ever ship a "live document scrubbing" feature where the user sees concepts appear as they read along.

## What I'd try next (if implementing)

1. Prototype against the eval set: run the concept extractor with `run_stream` on 5 representative documents, log the order in which concepts appear vs the final ordering.
2. If 80%+ of concepts arrive in final-order or close-to-it, ship streaming with a small reorder step at the end.
3. If concepts arrive in document-discovery order (out of importance order), buffer the first ~3s of stream, then emit. Loses some of the perceived-speed win but preserves UX.
4. If the model emits all-at-once anyway (no real streaming), abandon the design and don't ship.
5. Frontend change is small: extend the `progress:concept` handler to push chips into the row, dedupe by name.
