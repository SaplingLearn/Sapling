/**
 * One copy of a server-streamed page, at every moment.
 *
 * React's streaming server renderer (react-dom/server 19.2+, the version Next
 * bundles) outlines a large Suspense boundary: past its progressive chunk size
 * (12.8 KB) the boundary is sent as its fallback, and its content follows in a
 * hidden `<div id="S:n">`. The (shell) loading.tsx boundary around a big page
 * (/library, /settings, /achievements) is prerendered that way. The inline
 * runtime then QUEUES the reveal: `$RC` marks the boundary `$~` and pushes the
 * pair [boundary template, hidden content] onto `$RB`, and `$RV` reveals the
 * queue on a later frame or up to ~300 ms after the first paint (React batches
 * server reveals).
 *
 * React cannot hydrate a boundary that is still queued. When something above
 * it updates first — and right after hydration everything does: the shell's
 * providers change their contexts (the user read back, the flags loaded) and
 * Next's layout router re-renders the segment above the page — React gives up
 * on the server HTML and renders the page on the client, removing only the
 * boundary's fallback. The queued server copy stays in the document, hidden,
 * until the throttled reveal drops it: for up to ~300 ms the page exists twice
 * (two `library-upload` buttons in e2e/upload.spec.ts, one outside
 * NavFeatureGate).
 *
 * The guard runs React's own reveal (`$RV`) for everything queued, in the
 * hydration commit — before any of those updates can render — so the boundary
 * holds the server HTML and hydrates it. While the document can still
 * stream more boundaries in, it reveals each one the moment it is queued (or
 * drops its hidden copy at once, if React already rendered that boundary on
 * the client: `$RV` skips a boundary whose template is gone and removes its
 * content). It touches nothing when no boundary is queued, and a runtime of
 * another shape is left to its own timer.
 */
import { useLayoutEffect } from "react";

type StreamingRuntime = {
  /** Queued reveals, flat: [template, hidden content, template, …]. */
  $RB?: unknown[];
  /** Reveals (or drops) every queued pair, then empties the queue. */
  $RV?: (queue: unknown[]) => void;
};

function runtime(): StreamingRuntime {
  return window as unknown as StreamingRuntime;
}

function hasQueuedReveal(): boolean {
  const queue = runtime().$RB;
  return Array.isArray(queue) && queue.length > 0;
}

/** Reveal every server-rendered Suspense boundary React has queued, now. */
export function revealQueuedBoundaries(): void {
  const { $RB: queue, $RV: reveal } = runtime();
  if (!Array.isArray(queue) || queue.length === 0 || typeof reveal !== "function") return;
  try {
    reveal(queue);
  } catch {
    // Not the runtime this was written against: its own timer still reveals.
  }
}

/** Mounted once at the root of the app (StreamedRevealGuard). */
export function useStreamedRevealGuard(): void {
  useLayoutEffect(() => {
    revealQueuedBoundaries();
    // Until the document is complete no more boundary can arrive: once it is
    // and nothing is queued, there is nothing left to watch.
    const settled = () => document.readyState === "complete" && !hasQueuedReveal();
    if (settled()) return;
    // `$RC` writes the boundary's `$~` marker (characterData) as it queues it;
    // React rendering a boundary on the client removes its template (childList).
    const observer = new MutationObserver(() => {
      revealQueuedBoundaries();
      if (settled()) observer.disconnect();
    });
    observer.observe(document, { childList: true, characterData: true, subtree: true });
    return () => observer.disconnect();
  }, []);
}
