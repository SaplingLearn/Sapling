"use client";
/** The dashboard's streak week: the Monday-first days and each day's mark
 *  (moved out of screens/Dashboard.tsx). */
import { AnimatePresence, motion, type Target } from "framer-motion";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";

const STREAK_SHIELD_PATH =
  "M8 2.5 L23.5 3.8 Q28.8 4.3 28.3 9.6 L27 24.2 Q26.4 29.2 21.2 28.5 L8.2 27.4 Q3 26.9 3.6 21.7 L4.9 7.6 Q5.5 2.5 10.4 2.7 Z";

/** A day mark's rendered size, px (its viewBox is 32 units). */
const MARK_PX = 30;

type MarkState = "done" | "today" | "missed" | "future";

/**
 * One day's mark. When a day changes state (today's session ticks it done)
 * the new mark scales in over the old one; the first paint is still.
 */
export function StreakMark({ state, day }: { state: MarkState; day: number }) {
  const m = useMotionPresets();
  return (
    <AnimatePresence initial={false} mode="wait">
      <Mark key={state} state={state} day={day} motionProps={m.scaleIn} />
    </AnimatePresence>
  );
}

function Mark({ state, day, motionProps }: { state: MarkState; day: number; motionProps: MotionPreset }) {
  if (state === "done") {
    return (
      <motion.svg initial={motionProps.initial as Target} animate={motionProps.animate} exit={motionProps.exit} transition={motionProps.transition} viewBox="0 0 32 32" width={MARK_PX} height={MARK_PX} aria-label="completed">
        <path d={STREAK_SHIELD_PATH} fill="var(--alert-warn)" />
        <path
          d="M10.5 16.5 L14.2 20.2 L22 12.4"
          stroke="var(--text-on-fill)"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </motion.svg>
    );
  }
  if (state === "today") {
    return (
      <motion.svg initial={motionProps.initial as Target} animate={motionProps.animate} exit={motionProps.exit} transition={motionProps.transition} viewBox="0 0 32 32" width={MARK_PX} height={MARK_PX} aria-label="today">
        <circle cx="16" cy="16" r="13" fill="var(--alert-err)" />
        <path
          d="M16 10 V22 M10 16 H22"
          stroke="var(--text-on-fill)"
          strokeWidth="3"
          fill="none"
          strokeLinecap="round"
        />
      </motion.svg>
    );
  }
  return (
    <motion.svg initial={motionProps.initial as Target} animate={motionProps.animate} exit={motionProps.exit} transition={motionProps.transition} viewBox="0 0 32 32" width={MARK_PX} height={MARK_PX} aria-label={state === "missed" ? "missed" : "upcoming"}>
      <path
        d={STREAK_SHIELD_PATH}
        fill="none"
        stroke="var(--border)"
        strokeWidth="1.5"
      />
      <text
        x="16"
        y="20"
        textAnchor="middle"
        fontSize="11"
        fontWeight="500"
        fill="var(--text-muted)"
        opacity={state === "future" ? 0.5 : 1}
      >
        {day}
      </text>
    </motion.svg>
  );
}

export function getWeekDays(today: Date) {
  // Monday-first ISO week.
  const start = new Date(today);
  start.setHours(0, 0, 0, 0);
  const dow = (start.getDay() + 6) % 7; // 0=Mon
  start.setDate(start.getDate() - dow);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}
