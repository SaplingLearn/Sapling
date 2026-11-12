"use client";
/**
 * The guide's generation, as the reader follows it: the outline arrives, then
 * each section, then the finished guide. A guide that is still `generating`
 * when it loads is resumed; Update and Regenerate run the same stream.
 */
import React from "react";

import { useToast } from "@/components/ToastProvider";
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { generateGuide, getGuide, GuideGenerationError } from "@/lib/studyGuide/api";
import type { GenerateMode, GenerationStep, GuideDetail, GuideStatus } from "@/lib/studyGuide/types";

import { applyOutline, applySection } from "./guideEdits";
import type { GuideUpdate } from "./useGuide";

export interface GenerationState {
  /** A stream is running, or another tab's run is being followed. */
  active: boolean;
  label: string;
  /** Null until the first status event, and while following another tab. */
  step: GenerationStep | null;
  error: string | null;
}

const IDLE: GenerationState = { active: false, label: "", step: null, error: null };
const STARTING: GenerationState = { ...IDLE, active: true, label: "Getting your guide ready" };
const ELSEWHERE: GenerationState = { ...IDLE, active: true, label: "This guide is being written in another tab" };
const FAILED = "The guide could not be written.";
export const POLL_MS = 3000;

/** Resolves after `ms`, or rejects as soon as the signal aborts. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
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

/** Another tab is writing the guide: re-read it until that run ends. */
async function follow({ userId, guideId, signal, update }: Run): Promise<GuideDetail> {
  for (;;) {
    await wait(POLL_MS, signal);
    const fresh = await getGuide(userId, guideId);
    if (fresh.status !== "generating") return fresh;
    if (!signal.aborted) update(() => fresh);
  }
}

async function write(run: Run, mode: GenerateMode): Promise<GuideDetail> {
  const { userId, guideId, signal, update, setState } = run;
  try {
    return await generateGuide(userId, guideId, mode, {
      signal,
      onStatus: (label, step) => setState({ ...IDLE, active: true, label, step }),
      onOutline: content => update(guide => applyOutline(guide, content)),
      onSection: section => update(guide => applySection(guide, section)),
    });
  } catch (err) {
    if (statusOf(err) !== 409) throw err;
  }
  setState(ELSEWHERE);
  return follow(run);
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
