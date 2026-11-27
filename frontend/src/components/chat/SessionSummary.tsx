"use client";

import React from "react";
import { motion } from "framer-motion";
import type { SessionSummaryData } from "@/lib/api";
import { useMotionPresets } from "@/lib/motion";
import { useOverlayBehaviour } from "@/components/Dialog";
import styles from "./SessionSummary.module.css";

interface SessionSummaryProps {
  summary: SessionSummaryData;
  onClose: () => void;
}

/** PKG-14b (spec §11.2): the summary carries only what the backend fills —
 *  `concepts_covered` and `time_spent_minutes`. The three lists that were
 *  always empty (mastery changes, new connections, recommended next) are gone. */
export function SessionSummary({ summary, onClose }: SessionSummaryProps) {
  const { concepts_covered = [], time_spent_minutes = 0 } = summary || {};
  const m = useMotionPresets();
  // Dialog's modal engine: scroll lock, focus in and back out, Escape, Tab trap.
  const { panelRef, onKeyDown } = useOverlayBehaviour({ open: true, onClose });

  // The session just ended: the backdrop fades in and the dialog scales up
  // into place, then the concepts covered arrive one after another.
  return (
    <motion.div
      className={styles.backdrop}
      onClick={onClose}
      onKeyDown={onKeyDown}
      initial={m.fade.initial}
      animate={m.fade.animate}
      transition={m.fade.transition}
    >
      <motion.div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-summary-title"
        className={`card ${styles.dialog}`}
        onClick={e => e.stopPropagation()}
        initial={m.scaleIn.initial}
        animate={m.scaleIn.animate}
        transition={m.scaleIn.transition}
      >
        <div className={styles.header}>
          <div className="label-micro">Session summary</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div id="session-summary-title" className={`h-serif ${styles.title}`}>Nice session.</div>
        <div className={styles.time}>
          {time_spent_minutes > 0 ? `${time_spent_minutes} minute${time_spent_minutes === 1 ? "" : "s"} spent.` : "Session wrapped."}
        </div>

        {concepts_covered.length > 0 && (
          <section className={styles.section}>
            <div className={`label-micro ${styles.sectionLabel}`}>Concepts covered</div>
            <motion.div className={styles.chips} variants={m.list.container} initial="hidden" animate="shown">
              {concepts_covered.map(c => (
                <motion.span key={c} className={`chip ${styles.concept}`} variants={m.list.item}>
                  {c}
                </motion.span>
              ))}
            </motion.div>
          </section>
        )}

        <div className={styles.footer}>
          <button className="btn btn--primary" onClick={onClose}>Done</button>
        </div>
      </motion.div>
    </motion.div>
  );
}
