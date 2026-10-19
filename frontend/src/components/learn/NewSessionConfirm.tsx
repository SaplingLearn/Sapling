"use client";
// The confirmation before "New session" wraps up a session the learner is
// still in (redesign prompt 02). Cancel leaves the current session exactly as
// it was. Confirm runs `onConfirm`, which closes the open session; the dialog
// stays open (and cannot be dismissed) until that close settles, so a 409 or
// a failure is explained here and nothing new starts. Portal, focus trap,
// Escape and focus return are Dialog's `useOverlayBehaviour`, as ui/Sheet uses.
import React, { useRef } from "react";
import { createPortal } from "react-dom";

import { useOverlayBehaviour } from "../Dialog";
import { SaplingAction, StatusMessage } from "@/components/sapling";
import styles from "./LoopLearn.module.css";

export interface NewSessionConfirmProps {
  open: boolean;
  /** The topic a deep link offered, when this new session is for it. */
  topic?: string | null;
  /** The close is in flight: both actions disable and Escape does nothing. */
  busy: boolean;
  /** Why the open session could not be wrapped up (nothing was started). */
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function NewSessionConfirm({ open, topic, busy, error, onCancel, onConfirm }: NewSessionConfirmProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = React.useId();
  const bodyId = React.useId();
  const { mounted, visible, panelRef, onKeyDown } = useOverlayBehaviour({
    open,
    onClose: onCancel,
    dismissible: !busy,
    initialFocusRef: cancelRef,
  });
  if (!mounted || !open) return null;
  return createPortal(
    <div
      className={`sapling-surface ${styles.confirmBackdrop}`}
      data-visible={visible || undefined}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        if (!busy && event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        className={styles.confirmPanel}
        data-testid="loop-new-session-confirm"
      >
        <h2 id={titleId} className={styles.confirmTitle}>
          {topic ? `Start a session on ${topic}?` : "Start a new session?"}
        </h2>
        <p id={bodyId} className={styles.confirmBody}>
          Your current session will be wrapped up first, and its progress saved. The new session starts with a fresh
          check-in and its own goal.
        </p>
        {busy && <StatusMessage tone="pending">Wrapping up your current session…</StatusMessage>}
        {error && (
          <StatusMessage tone="error" title="Nothing new was started" testid="loop-new-session-error">
            {error}
          </StatusMessage>
        )}
        <div className={styles.confirmActions}>
          <SaplingAction
            ref={cancelRef}
            tone="secondary"
            data-testid="loop-new-session-cancel"
            disabled={busy}
            onClick={onCancel}
          >
            Keep this session
          </SaplingAction>
          <SaplingAction data-testid="loop-new-session-confirm-start" disabled={busy} onClick={onConfirm}>
            {busy ? "Wrapping up…" : error ? "Try again" : "Wrap up and start new"}
          </SaplingAction>
        </div>
      </div>
    </div>,
    document.body,
  );
}
