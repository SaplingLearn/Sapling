"use client";
import React, { useLayoutEffect, useRef } from "react";
import { modalOpen } from "./modalOpen";
import styles from "./CenteredCard.module.css";

/** A card that stands in for the screen: an error, the saved-grade recovery,
 *  no course, the start's crisis-support card, a session closed elsewhere.
 *  Spec §13 A135: when it replaces the control the student used (focus was left
 *  on the page, or on a control the action disabled), its heading takes focus,
 *  so it is read out and Tab continues from it. */
export function CenteredCard({ testId, children }: { testId: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const active = document.activeElement;
    if (modalOpen() || (active && active !== document.body && !active.matches(":disabled"))) return;
    const heading = ref.current?.querySelector<HTMLElement>("h2, h3");
    if (!heading) {
      ref.current?.focus();
      return;
    }
    if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
    heading.focus();
  }, []);
  return (
    <div className={styles.scroll}>
      <div ref={ref} tabIndex={-1} data-testid={testId} className={`card fade-in ${styles.card}`}>
        {children}
      </div>
    </div>
  );
}
