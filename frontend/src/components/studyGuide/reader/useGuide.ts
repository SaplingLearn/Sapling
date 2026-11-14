"use client";
/**
 * One guide, loaded, and the small state changes the reader makes to it:
 * read marks, saving to the Library, feedback.
 */
import React from "react";

import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import { getGuide, patchGuide } from "@/lib/studyGuide/api";
import type { Feedback, GuideDetail } from "@/lib/studyGuide/types";

import { toggleRead } from "./guideEdits";

export type GuideUpdate = (edit: (guide: GuideDetail) => GuideDetail) => void;

const NOT_SAVED = "That could not be saved. Try again.";

export function useGuide(userId: string, guideId: string) {
  const toast = useToast();
  /** Null while loading. */
  const [guide, setGuide] = React.useState<GuideDetail | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!userId) return;
    let live = true;
    getGuide(userId, guideId)
      .then(loaded => live && setGuide(loaded))
      .catch(err => live && setError(humanizeError(err, "This guide could not be loaded.")));
    return () => {
      live = false;
    };
  }, [userId, guideId]);

  const update = React.useCallback<GuideUpdate>(edit => setGuide(current => current && edit(current)), []);

  /** Shows at once, and rolls back when the save fails. */
  const onToggleRead = (sectionId: string) => {
    if (!guide) return;
    const next = toggleRead(guide.read_sections, sectionId);
    update(current => ({ ...current, read_sections: next }));
    patchGuide(userId, guideId, { read_sections: next }).catch(() => {
      update(current => ({ ...current, read_sections: toggleRead(current.read_sections, sectionId) }));
      toast.error(NOT_SAVED);
    });
  };

  const save = async () => {
    try {
      const state = await patchGuide(userId, guideId, { saved: true });
      update(current => ({ ...current, saved_at: state.saved_at }));
    } catch {
      toast.error("This guide could not be saved to your Library. Try again.");
    }
  };

  const sendFeedback = (feedback: Feedback) => {
    const before = guide?.feedback ?? null;
    update(current => ({ ...current, feedback }));
    patchGuide(userId, guideId, { feedback }).catch(() => {
      update(current => ({ ...current, feedback: before }));
      toast.error(NOT_SAVED);
    });
  };

  return { guide, error, update, toggleRead: onToggleRead, save, sendFeedback };
}
