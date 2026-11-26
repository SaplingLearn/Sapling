"use client";
import { useEffect, useState } from "react";
import { useUser } from "@/context/UserContext";
import { useFlag } from "@/context/FlagsContext";
import { getStudyNext } from "@/lib/studyApi";

/**
 * W3.3b: learner-next due ids for Practice what's due on wrap-up. Empty while
 * flags off / unread / failed — closeHandoffCtas then uses course+start.
 */
export function usePracticeDueIds(courseId: string | null, enabled: boolean): readonly string[] {
  const { userId } = useUser();
  const loopOn = useFlag("learning_loop") === "on";
  const planOn = useFlag("quiz_concept_plan") === "on";
  const [ids, setIds] = useState<readonly string[]>([]);
  // Switched off (or nothing to read for): drop the last answer during render
  // rather than in the effect, so it never shows for a render.
  const active = enabled && !!courseId && !!userId && loopOn && planOn;
  if (!active && ids.length > 0) setIds([]);
  useEffect(() => {
    if (!enabled || !courseId || !userId || !loopOn || !planOn) return;
    let live = true;
    getStudyNext(userId, courseId)
      .then((r) => {
        if (live) setIds(r.due.map((c) => c.node_id));
      })
      .catch(() => {
        if (live) setIds([]);
      });
    return () => {
      live = false;
    };
  }, [enabled, courseId, userId, loopOn, planOn]);
  return ids;
}
