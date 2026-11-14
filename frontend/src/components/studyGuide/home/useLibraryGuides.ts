"use client";
import React from "react";

import { useFlagMap } from "@/context/FlagsContext";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";

export interface LibraryGuidesState {
  /** Every guide the student has; the Library shows the saved ones. */
  guides: GuideCard[];
  /** The list has answered, or there is none to ask for: an empty one now means no guides. */
  known: boolean;
  /** The list could not be read. */
  failed: boolean;
  /** Reads the list again. */
  reload: () => void;
}

/**
 * The guides for the Library, read on their own so the documents never wait
 * on them. Nothing is read while a flag hides Study: the server answers every
 * study guide call with a 404 then, and there is nothing to show.
 */
export function useLibraryGuides(userId: string): LibraryGuidesState {
  const { flags, ready } = useFlagMap();
  const hidden = ready && flags.hide_study === "on";
  const asked = ready && !hidden;
  const [guides, setGuides] = React.useState<GuideCard[]>([]);
  const [status, setStatus] = React.useState<"loading" | "ready" | "failed">("loading");
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    if (!userId || !asked) return;
    let live = true;
    listGuides(userId)
      .then(r => {
        if (!live) return;
        setGuides(r.guides);
        setStatus("ready");
      })
      .catch(err => {
        console.error("library guides load failed", err);
        if (live) setStatus("failed");
      });
    return () => { live = false; };
  }, [userId, asked, attempt]);

  const reload = React.useCallback(() => {
    setStatus("loading");
    setAttempt(n => n + 1);
  }, []);
  if (hidden) return { guides: [], known: true, failed: false, reload };
  return { guides, known: status === "ready", failed: status === "failed", reload };
}
