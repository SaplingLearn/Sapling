/**
 * One generation request, followed to the finished guide, and what its
 * failure leaves the reader able to do. No React here: useGeneration drives it.
 */
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { generateGuide, getGuide, GuideGenerationError, type GenerationHandlers } from "@/lib/studyGuide/api";
import type { GenerateMode, GuideDetail, GuideStatus } from "@/lib/studyGuide/types";

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
  /** The server still has a finished guide, so the banner can be put away. */
  dismissible: boolean;
}

/**
 * `status` is the guide's as the server has it once the run has stopped, or
 * null when it could not be read.
 *
 * A guide that is `generating` or `failed` is partly written. Only a resume
 * finishes it, so Retry is always there and asks for one, whatever stopped
 * the run: the banner cannot be put away, and without Retry the student
 * could do nothing short of a reload.
 *
 * A guide that is still `ready` was not replaced: an Update or a Regenerate
 * saves nothing until its first section is written. Retry asks for the same
 * thing again, unless the server said that cannot help. A 422 is the server
 * saying the request itself cannot work (an Update with nothing new to add):
 * Retry would get the same answer.
 */
export function failureOf(err: unknown, mode: GenerateMode, status: GuideStatus | null): Failure {
  const streamed = err instanceof GuideGenerationError;
  const message = streamed ? err.message : humanizeError(err, FAILED);
  if (status === "generating" || status === "failed") return { message, retry: "resume", dismissible: false };
  const retryable = streamed ? err.retryable : statusOf(err) !== 422;
  return { message, retry: retryable ? mode : null, dismissible: status === "ready" };
}

/** A ready guide with every section written: a resume has nothing to add to it. */
function isFinished(guide: GuideDetail): boolean {
  return guide.status === "ready" && guide.content.sections.every(section => section.status === "written");
}

/**
 * A run stopped. What its stream showed is not always what was saved (the
 * outline of a failed Update or Regenerate never was), so the guide is read
 * again. `guide` is null when that fails too: the reader keeps what it has.
 *
 * `failure` is null when nothing failed after all: a resume was turned away,
 * or cut, because another request had finished the guide first.
 */
export async function failedRun(
  { userId, guideId, mode }: Pick<Run, "userId" | "guideId" | "mode">,
  err: unknown,
): Promise<{ guide: GuideDetail | null; failure: Failure | null }> {
  const guide = await getGuide(userId, guideId).catch(() => null);
  if (guide && mode === "resume" && isFinished(guide)) return { guide, failure: null };
  return { guide, failure: failureOf(err, mode, guide?.status ?? null) };
}
