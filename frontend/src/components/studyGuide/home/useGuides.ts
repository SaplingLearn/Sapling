"use client";
import React from "react";

import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { useLatestRequest } from "@/lib/useLatestRequest";

export interface GuidesState {
  guides: GuideCard[];
  /** The list has not answered yet (first load, or a retry). */
  loading: boolean;
  /** The last load failed: an empty list here is not "no guides". */
  failed: boolean;
  reload: () => void;
}

/** The student's guides. A reload racing an older one resolves to the latest. */
export function useGuides(userId: string): GuidesState {
  const [guides, setGuides] = React.useState<GuideCard[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const req = useLatestRequest();

  const reload = React.useCallback(() => {
    if (!userId) return;
    const run = req.begin();
    setLoading(true);
    listGuides(userId)
      .then(r => {
        if (!run.isCurrent()) return;
        setGuides(r.guides || []);
        setFailed(false);
      })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("study guides load failed", err);
        setFailed(true);
      })
      .finally(() => {
        if (run.isCurrent()) setLoading(false);
      });
  }, [userId, req]);

  React.useEffect(reload, [reload]);

  return { guides, loading, failed, reload };
}
