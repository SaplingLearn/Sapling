"use client";
/**
 * The guide's generation, as the reader follows it: the outline arrives, then
 * each section, then the finished guide. A guide that is still `generating`
 * when it loads is resumed; Update and Regenerate run the same stream. While
 * another run holds the guide, the reader shows what that run has written and
 * keeps asking to resume, so it takes over if that run stops.
 */
import React from "react";

import { useToast } from "@/components/ToastProvider";
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { generateGuide, getGuide, GuideGenerationError, type GenerationHandlers } from "@/lib/studyGuide/api";
import type { GenerateMode, GenerationStep, GuideDetail, GuideStatus } from "@/lib/studyGuide/types";

import { applyOutline, applySection } from "./guideEdits";
import type { GuideUpdate } from "./useGuide";

export interface GenerationState {
  /** A stream is running, or another run is being waited on. */
  active: boolean;
  label: string;
  /** Null until the first status event, and while another run is writing. */
  step: GenerationStep | null;
  error: string | null;
}

const IDLE: GenerationState = { active: false, label: "", step: null, error: null };
const STARTING: GenerationState = { ...IDLE, active: true, label: "Getting your guide ready" };
const ELSEWHERE: GenerationState = { ...IDLE, active: true, label: "This guide is being written in another tab" };
const FAILED = "The guide could not be written.";
/** How long to wait before asking again while another run holds the guide. */
export const RETRY_MS = 3000;

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

interface Run {
  userId: string;
  guideId: string;
  signal: AbortSignal;
  update: GuideUpdate;
  setState: (state: GenerationState) => void;
}

/**
 * Write the guide and resolve with it once it is done.
 *
 * A 409 means another run holds the guide. Re-read it, so the sections that
 * run has written show, then wait and ask to resume. Asking again, not only
 * re-reading, is what picks the guide up when the tab that was writing it
 * closes: its claim lapses and this request takes it.
 */
async function write(run: Run, mode: GenerateMode): Promise<GuideDetail> {
  const { userId, guideId, signal, update, setState } = run;
  const handlers: GenerationHandlers = {
    signal,
    onStatus: (label, step) => setState({ ...IDLE, active: true, label, step }),
    onOutline: content => update(guide => applyOutline(guide, content)),
    onSection: section => update(guide => applySection(guide, section)),
  };
  for (let next = mode; ; next = "resume") {
    try {
      return await generateGuide(userId, guideId, next, handlers);
    } catch (err) {
      if (statusOf(err) !== 409) throw err;
    }
    setState(ELSEWHERE);
    const fresh = await getGuide(userId, guideId);
    if (fresh.status !== "generating") return fresh;
    if (!signal.aborted) update(() => fresh);
    await wait(RETRY_MS, signal);
  }
}

const AT_LOAD: Record<GuideStatus, GenerationState> = {
  generating: STARTING,
  ready: IDLE,
  failed: { ...IDLE, error: FAILED },
};

/**
 * `status` is the guide's status as the server last gave it. The reader's own
 * edits never change it, so an Update or a Regenerate does not look like a
 * guide to resume.
 */
export function useGeneration(userId: string, guideId: string, status: GuideStatus, update: GuideUpdate) {
  const toast = useToast();
  const [state, setState] = React.useState<GenerationState>(AT_LOAD[status]);
  /** An Update finished during this visit. */
  const [updated, setUpdated] = React.useState(false);
  const controller = React.useRef<AbortController | null>(null);

  const start = React.useCallback(
    async (mode: GenerateMode) => {
      controller.current?.abort();
      const { signal } = (controller.current = new AbortController());
      setState(STARTING);
      // StrictMode mounts twice in development. Let the first mount's cleanup
      // land before a request goes out, or its claim makes the second one 409.
      await Promise.resolve();
      if (signal.aborted) return;
      try {
        const finished = await write({ userId, guideId, signal, update, setState }, mode);
        if (signal.aborted) return;
        update(() => finished);
        if (finished.status === "failed") throw new Error(FAILED);
        setState(IDLE);
        setUpdated(mode === "update");
        toast.success("Guide ready.");
      } catch (err) {
        if (signal.aborted) return;
        const reason = err instanceof GuideGenerationError ? err.message : humanizeError(err, FAILED);
        setState({ ...IDLE, error: reason });
      }
    },
    [userId, guideId, update, toast],
  );

  const resume = status === "generating";
  React.useEffect(() => {
    if (resume) void start("resume");
    return () => controller.current?.abort();
  }, [resume, start]);

  return { ...state, updated, start };
}
