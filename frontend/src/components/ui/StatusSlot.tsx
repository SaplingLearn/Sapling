"use client";
import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";

// One status slot per region (Tutor redesign phase 2; the audit's anti-clutter
// rule "one status slot per region, prioritized"): the caller lists its
// notices most important first, and the slot shows the first one that is on.
// When it clears, the next one takes its place, so two notices never stack
// and the student reads one sentence and its action at a time.
//
// The slot itself is always in the DOM as a polite live region (spec §13
// A135): a notice is announced when it is added to a region that was already
// there, not reliably when it arrives together with its region.

export type StatusNotice = {
  /** Stable per notice: the slot animates between notices by key. */
  key: string;
  /** Off notices are skipped; the first one on is shown. */
  on: boolean;
  render: () => React.ReactNode;
};

export type StatusSlotProps = {
  notices: readonly StatusNotice[];
  testId?: string;
  className?: string;
};

export function StatusSlot({ notices, testId, className }: StatusSlotProps) {
  const m = useMotionPresets();
  const shown = notices.find((n) => n.on) ?? null;
  return (
    <div
      aria-live="polite"
      data-testid={testId}
      data-has-notices={shown !== null}
      data-notice={shown?.key ?? ""}
      className={className}
    >
      {/* The bare wrapper carries the height tween, so a padded notice
          collapses to nothing rather than to its padding. */}
      <AnimatePresence initial={false}>
        {shown && (
          <motion.div key={shown.key} {...m.collapse}>
            {shown.render()}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
