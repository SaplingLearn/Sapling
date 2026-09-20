"use client";

/**
 * The one door out of a live attempt (§5 B2).
 *
 * Nothing else in the question screen navigates: the machine refuses `EXIT`
 * from `active`/`answered` (invariant 1), so leaving has to come through here
 * and land on `paused`. The dialog exists to make that deliberate — and to say
 * the true thing about it, which is that the answers already given are safe.
 *
 * "Keep going" is the primary and takes focus: the safe choice is the default
 * one, and Escape / the backdrop / the close button all resolve to it.
 */

import React, { useRef } from "react";
import Dialog from "@/components/Dialog";

export interface LeaveDialogProps {
  open: boolean;
  /** Escape, the backdrop, the close button and "Keep going" all land here. */
  onCancel: () => void;
  onConfirm: () => void;
}

export function LeaveDialog({ open, onCancel, onConfirm }: LeaveDialogProps) {
  // Without this the overlay focuses the first focusable node in the panel,
  // which is Dialog's own close button. The safe action should be the one
  // under the student's fingers.
  const keepGoingRef = useRef<HTMLButtonElement>(null);

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      size="sm"
      title="Leave this quiz?"
      initialFocusRef={keepGoingRef}
    >
      <div data-testid="quiz-leave-dialog">
        <p className="quiz-leave-dialog__body">
          Your answers so far are saved. You can pick it up again from Quiz home.
        </p>
        <div className="quiz-leave-dialog__actions">
          <button
            ref={keepGoingRef}
            type="button"
            className="btn btn--primary"
            data-testid="quiz-leave-cancel"
            onClick={onCancel}
          >
            Keep going
          </button>
          <button
            type="button"
            className="btn"
            data-testid="quiz-leave-confirm"
            onClick={onConfirm}
          >
            Leave
          </button>
        </div>
      </div>
    </Dialog>
  );
}
