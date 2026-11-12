"use client";
/**
 * The guide's generation, as the reader follows it: the outline arrives, then
 * each section, then the finished guide. A guide that is still `generating`
 * when it loads is resumed; Update and Regenerate run the same stream. While
 * another run holds the guide, the reader shows what that run has written and
 * keeps asking, so it takes over if that run stops.
 */
import React from "react";

import { useToast } from "@/components/ToastProvider";
import type { GenerationHandlers } from "@/lib/studyGuide/api";
import type { GenerateMode, GenerationStep, GuideDetail, GuideStatus } from "@/lib/studyGuide/types";

import { FAILED, failureOf, writeGuide, type Failure } from "./generationRun";
import { applyOutline, applySection } from "./guideEdits";
import type { GuideUpdate } from "./useGuide";

export interface GenerationState {
  /** A stream is running, or another run is being waited on. */
  active: boolean;
  label: string;
  /** Null until the first status event, and while another run is writing. */
  step: GenerationStep | null;
  failure: Failure | null;
}

const IDLE: GenerationState = { active: false, label: "", step: null, failure: null };
const STARTING: GenerationState = { ...IDLE, active: true, label: "Getting your guide ready" };
const ELSEWHERE: GenerationState = { ...IDLE, active: true, label: "This guide is being written in another tab" };

const AT_LOAD: Record<GuideStatus, GenerationState> = {
  generating: STARTING,
  ready: IDLE,
  failed: { ...IDLE, failure: { message: FAILED, retry: "resume", replanned: false } },
};

/**
 * `status` is the guide's status as the server last gave it. The reader's own
 * edits never change it, so an Update or a Regenerate does not look like a
 * guide to resume.
 */
export function useGeneration(userId: string, guideId: string, status: GuideStatus, update: GuideUpdate) {
  const toast = useToast();
  const [state, setState] = React.useState<GenerationState>(AT_LOAD[status]);
  /** The sections this run is done with, written or not. */
  const [tried, setTried] = React.useState<string[]>([]);
  /** An Update finished during this visit. */
  const [updated, setUpdated] = React.useState(false);
  const controller = React.useRef<AbortController | null>(null);

  const start = React.useCallback(
    async (mode: GenerateMode) => {
      controller.current?.abort();
      const { signal } = (controller.current = new AbortController());
      let replanned = false;
      setState(STARTING);
      setTried([]);
      // StrictMode mounts twice in development. Let the first mount's cleanup
      // land before a request goes out, or its claim makes the second one 409.
      await Promise.resolve();
      if (signal.aborted) return;
      const handlers: GenerationHandlers & { signal: AbortSignal } = {
        signal,
        onStatus: (label, step) => setState({ ...IDLE, active: true, label, step }),
        onOutline: content => {
          replanned = true;
          update(guide => applyOutline(guide, content));
        },
        onSection: section => {
          setTried(ids => [...ids, section.id]);
          update(guide => applySection(guide, section));
        },
      };
      const onHeld = (fresh: GuideDetail) => {
        if (signal.aborted) return;
        setState(ELSEWHERE);
        update(() => fresh);
      };
      try {
        const finished = await writeGuide({ userId, guideId, mode, handlers, onHeld });
        if (signal.aborted) return;
        update(() => finished);
        if (finished.status === "failed") throw new Error(FAILED);
        setState(IDLE);
        setUpdated(mode === "update");
        toast.success("Guide ready.");
      } catch (err) {
        if (signal.aborted) return;
        setState({ ...IDLE, failure: failureOf(err, mode, replanned) });
      }
    },
    [userId, guideId, update, toast],
  );

  const resume = status === "generating";
  React.useEffect(() => {
    if (resume) void start("resume");
    return () => controller.current?.abort();
  }, [resume, start]);

  /** Put the failure away. The guide stays as it is. */
  const dismiss = React.useCallback(() => setState(IDLE), []);

  return { ...state, tried, updated, start, dismiss };
}
