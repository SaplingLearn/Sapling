"use client";
import React from "react";

import { humanizeError } from "@/lib/errorMessage";
import { createGuide } from "@/lib/studyGuide/api";
import type { GuideRequest } from "@/lib/studyGuide/types";

export interface CreateGuide {
  submitting: boolean;
  /** Why the last try created nothing. */
  error: string | null;
  submit: (request: GuideRequest) => Promise<void>;
}

/** Creates the guide's row. Writing it is the reader's job, so a success
 *  hands the new id on and the dialog's choices are left as they were. */
export function useCreateGuide(userId: string, onCreated: (guideId: string) => void): CreateGuide {
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  /** The dialog is still there. It is unmounted when it closes. */
  const open = React.useRef(true);
  React.useEffect(() => {
    open.current = true;
    return () => {
      open.current = false;
    };
  }, []);

  const submit = async (request: GuideRequest) => {
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await createGuide(userId, request);
      // Closed meanwhile: the student chose to stay. The guide's row exists
      // and waits on the home, not finished, until it is opened.
      if (open.current) onCreated(id);
    } catch (err) {
      console.error("study guide create failed", err);
      if (!open.current) return;
      setError(humanizeError(err, "Couldn't start the guide. Try again."));
      setSubmitting(false);
    }
  };

  return { submitting, error, submit };
}
