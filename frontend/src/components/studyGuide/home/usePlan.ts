"use client";
import React from "react";

import { planGuide } from "@/lib/studyGuide/api";
import type { GuidePlan, GuideRequest } from "@/lib/studyGuide/types";

/** How long the choices must rest before the outline is planned again. */
export const PLAN_DEBOUNCE_MS = 300;

export interface PlanState {
  /** The outline for the choices, or the last one for the same class and term
   *  while the next is planned. */
  plan: GuidePlan | null;
  /** The outline shown is not yet the one for the current choices. */
  loading: boolean;
  failed: boolean;
}

type Answer = { request: GuideRequest; plan: GuidePlan | null };

/**
 * The planned outline for a request (null: nothing to plan yet). A change
 * waits `PLAN_DEBOUNCE_MS`, aborts the call before it and owns the answer.
 * `request` must keep its identity while its content is the same.
 */
export function usePlan(userId: string, request: GuideRequest | null): PlanState {
  const [answer, setAnswer] = React.useState<Answer | null>(null);

  React.useEffect(() => {
    if (!userId || !request) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      planGuide(userId, request, controller.signal)
        .then(plan => { if (!controller.signal.aborted) setAnswer({ request, plan }); })
        .catch(err => {
          if (controller.signal.aborted) return;
          console.error("study guide plan failed", err);
          setAnswer({ request, plan: null });
        });
    }, PLAN_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [userId, request]);

  if (!request) return { plan: null, loading: false, failed: false };
  const current = answer?.request === request;
  // The last outline stands in while the next is planned only for the same
  // class and term. Another class's sections under this one's choices are not
  // a late answer but a wrong one.
  const sameClass = answer?.request.course_id === request.course_id && answer?.request.semester === request.semester;
  return { plan: sameClass ? answer?.plan ?? null : null, loading: !current, failed: current && answer?.plan === null };
}
