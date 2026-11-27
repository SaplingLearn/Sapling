"use client";
import React, { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import styles from "./tutor.module.css";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A phone: the tutor sidebar as a modal drawer over the whole app (a portal,
 * so the app's own top bar cannot cover its head). It is a dialog
 * (`aria-modal`, so LoopLearn's `modalOpen()` sees it and nothing behind it
 * takes focus): while it is open everything else on the page is inert, Tab
 * cycles inside it, and Escape or a tap on the scrim closes it (`onClose`,
 * which hands focus back to the control that opened it). Opening it moves
 * focus to its first control.
 */
export function TutorDrawer({ label, onClose, children }: { label: string; onClose: () => void; children: React.ReactNode }) {
  const scrimRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const scrim = scrimRef.current;
    const behind = Array.from(document.body.children).filter((el) => el !== scrim && !el.hasAttribute("inert"));
    for (const el of behind) el.setAttribute("inert", "");
    panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => {
      for (const el of behind) el.removeAttribute("inert");
    };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !panelRef.current?.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !panelRef.current?.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div ref={scrimRef} className={styles.drawerScrim} data-testid="tutor-drawer-scrim" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        data-testid="tutor-drawer"
        className={styles.drawer}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
