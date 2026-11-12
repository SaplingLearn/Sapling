"use client";
import React from "react";
import { createPortal } from "react-dom";
import { useOverlayBehaviour } from "@/components/Dialog";
import s from "./StudyModal.module.css";

/**
 * StudyModal — the shell of the Study hub's centred modal (Exams and
 * Deadlines; the Quiz / Flashcards concept picker that shared it is gone).
 *
 * It used to be an absolutely positioned backdrop + card inside the hub, so
 * the scrim covered the hub's box rather than the viewport (a paper band below
 * it on a short or scrolled page), nothing animated, and Escape did nothing.
 * This portals to <body> with a fixed overlay and takes every modal behaviour
 * — scroll-lock, focus trap, initial focus, focus restore, Escape — from
 * `Dialog`'s `useOverlayBehaviour`, so it can't drift from the app's other
 * modals. Clicking the scrim closes it, as before. The entrance animation is
 * Dialog's, as a keyframe (see StudyModal.module.css for why).
 */
export interface StudyModalProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name of the dialog. */
  label: string;
  /** Card width in px; capped at the viewport. */
  width: number;
  /** Card max height in px; the card scrolls inside itself past it. */
  maxHeight: number;
  /** Distance from the viewport top in px (capped at 12vh). */
  top: number;
  /** Gap between the card's direct children. */
  gap: number;
  /** Focused when the modal opens, if it is mounted by then; otherwise the
   *  first focusable element is (Dialog's default). */
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  children: React.ReactNode;
}

export function StudyModal({ open, onClose, label, width, maxHeight, top, gap, initialFocusRef, children }: StudyModalProps) {
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose, initialFocusRef });

  if (!mounted || !open) return null;

  return createPortal(
    <div
      className={s.overlay}
      onKeyDown={onKeyDown}
      style={{
        zIndex: 100,
        "--study-modal-top": `${top}px`,
        "--study-modal-width": `${width}px`,
        "--study-modal-max-h": `${maxHeight}px`,
      } as React.CSSProperties}
    >
      <div className={s.backdrop} data-testid="study-modal-backdrop" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={s.dialog}
        style={{ gap }}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
