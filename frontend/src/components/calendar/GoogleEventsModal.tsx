"use client";
// The Calendar's "View Google events" modal (moved out of screens/Calendar.tsx
// unchanged, so the redesigned calendar shares it).
import React from "react";
import { motion, type MotionProps } from "framer-motion";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import { useScrollLock } from "@/lib/useScrollLock";
import type { GoogleEvent } from "@/lib/api";
import { Icon } from "../Icon";
import styles from "../screens/Calendar.module.css";

const asProps = (p: MotionPreset): MotionProps => p as MotionProps;

/** How far ahead "View Google events" looks, in days (the modal's copy says it too). */
export const GOOGLE_EVENTS_DAYS = 60;
/** A Google event's description is cut to this many characters in the modal. */
const DESCRIPTION_PREVIEW_CHARS = 140;

export function GoogleEventsModal({
  events, onClose,
}: {
  events: GoogleEvent[];
  onClose: () => void;
}) {
  // This modal only exists while it's open, so the lock is unconditional.
  useScrollLock(true);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const m = useMotionPresets();
  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className={styles.scrim}
      {...asProps(m.fade)}
    >
      <motion.div onClick={e => e.stopPropagation()} className={styles.modal} {...asProps(m.scaleIn)}>
        <div className={styles.modalHead}>
          <div className="label-micro">Upcoming Google Calendar events</div>
          <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" size={12} /> Close
          </button>
        </div>
        <div className={styles.modalBody}>
          {events.length === 0 ? (
            <div className={styles.modalEmpty}>No upcoming events in the next {GOOGLE_EVENTS_DAYS} days.</div>
          ) : (
            <motion.div
              className={styles.eventList}
              variants={m.list.container}
              initial="hidden"
              animate="shown"
            >
              {events.map(e => (
                <motion.div key={e.google_event_id} className={`card ${styles.event}`} variants={m.list.item}>
                  <div className={styles.eventHead}>
                    <div className={styles.eventTitle}>{e.title}</div>
                    <span className={`chip ${styles.eventTime}`}>
                      {e.all_day ? "All day" : e.start_datetime?.slice(11, 16) || ""}
                    </span>
                  </div>
                  <div className={styles.eventWhen}>
                    {e.start_date} {e.end_date && e.end_date !== e.start_date ? `→ ${e.end_date}` : ""}
                    {e.location ? ` · ${e.location}` : ""}
                  </div>
                  {e.description && (
                    <div className={styles.eventDesc}>
                      {e.description.length > DESCRIPTION_PREVIEW_CHARS
                        ? e.description.slice(0, DESCRIPTION_PREVIEW_CHARS) + "…"
                        : e.description}
                    </div>
                  )}
                  {e.html_link && (
                    <a href={e.html_link} target="_blank" rel="noreferrer" className={styles.eventLink}>
                      Open in Google Calendar →
                    </a>
                  )}
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
