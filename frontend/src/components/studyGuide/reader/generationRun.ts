/**
 * One generation request, followed to the finished guide, and what its
 * failure leaves the reader able to do. No React here: useGeneration drives it.
 */
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { generateGuide, getGuide, GuideGenerationError, type GenerationHandlers } from "@/lib/studyGuide/api";
import type { GenerateMode, GuideDetail } from "@/lib/studyGuide/types";

export const FAILED = "The guide could not be written.";
const STILL_HELD = "This guide is still being written somewhere else. Try again in a moment.";
/** How long to wait before asking again while another run holds the guide. */
export const RETRY_MS = 3000;
/** How many times an Update or a Regenerate asks for a held guide before it gives up. */
export const MAX_TRIES = 10;

/** Resolves after `ms`, or rejects as soon as the signal aborts. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    // An abort that has already happened fires no event.
    if (signal.aborted) return reject(signal.reason);
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason);
      },
      { once: true },
    );
  });
}

export interface Run {
  userId: string;
  guideId: string;
  mode: GenerateMode;
  /** The stream's callbacks, and the signal that stops the run. */
  handlers: GenerationHandlers & { signal: AbortSignal };
  /** Another run holds the guide. `fresh` is the guide as that run has left it. */
  onHeld: (fresh: GuideDetail) => void;
}

/**
 * Write the guide and resolve with it once it is done.
 *
 * A 409 means another run holds the guide. Re-read it, so what that run has
 * written shows, then wait and ask again. Asking again, not only re-reading,
 * is what picks the guide up when the tab that was writing it closes: its
 * claim lapses and this request takes it.
 *
 * A resume has nothing left to do once that run has finished, so the guide it
 * re-reads is its result. An Update or a Regenerate still has its own work to
 * do (the guide may only have been held while one block was rewritten): it
 * keeps asking for the same thing, and gives up after `MAX_TRIES`.
 */
export async function writeGuide({ userId, guideId, mode, handlers, onHeld }: Run): Promise<GuideDetail> {
  for (let tries = 1; ; tries++) {
    try {
      return await generateGuide(userId, guideId, mode, handlers);
    } catch (err) {
      if (statusOf(err) !== 409) throw err;
    }
    const fresh = await getGuide(userId, guideId);
    if (mode === "resume" && fresh.status !== "generating") return fresh;
    if (mode !== "resume" && tries >= MAX_TRIES) throw new GuideGenerationError(STILL_HELD, true);
    onHeld(fresh);
    await wait(RETRY_MS, handlers.signal);
  }
}

/** Why a generation stopped, and what can be done about it. */
export interface Failure {
  message: string;
  /** What Retry asks for. Null when asking again cannot help. */
  retry: GenerateMode | null;
  /** The run's outline had replaced the guide's sections before it stopped. */
  replanned: boolean;
}

/**
 * A run that stopped before its outline arrived changed nothing, so Retry
 * asks for the same thing again. After the outline the guide is half
 * rewritten on the server, and only a resume finishes it.
 *
 * A 422 is the server saying the request itself cannot work (an Update with
 * nothing new to add): Retry would get the same answer.
 */
export function failureOf(err: unknown, mode: GenerateMode, replanned: boolean): Failure {
  const streamed = err instanceof GuideGenerationError;
  const retryable = streamed ? err.retryable : statusOf(err) !== 422;
  return {
    message: streamed ? err.message : humanizeError(err, FAILED),
    retry: retryable ? (replanned ? "resume" : mode) : null,
    replanned,
  };
}
