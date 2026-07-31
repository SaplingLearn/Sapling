"use client";
import React from "react";
import { AnimatePresence, motion, MotionGlobalConfig } from "framer-motion";
import { IS_TEST_MODE } from "@/lib/testMode";

// Deterministic DOM for browser tests (#383): framer-motion's own test
// seam jumps every animation straight to its final keyframe. No-op in
// production builds (flag inlined to false at build time).
if (IS_TEST_MODE) MotionGlobalConfig.skipAnimations = true;

/**
 * The Study screen's framer-motion subtree, split out so the library stays
 * out of Study's initial bundle (#111) — Study.tsx loads both components
 * via next/dynamic (the MarkdownChat pattern).
 */

/** Sliding highlight behind the active Study Guide / Flashcards toggle
 *  button (spring layout animation between the two buttons). */
export function StudyToggleHighlight() {
  return (
    <motion.span
      layoutId="study-toggle-active"
      transition={{ type: "spring", stiffness: 380, damping: 32 }}
      style={{
        position: "absolute",
        inset: 0,
        background: "var(--accent-soft)",
        zIndex: -1,
      }}
    />
  );
}

/** Cross-fades the guide/cards panes when the mode toggles — old pane exits
 *  up, new pane enters from below; mode="wait" so they never overlap. */
export function StudyModePanel({
  mode,
  children,
}: {
  mode: string;
  children: React.ReactNode;
}) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={mode}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.22, ease: [0.2, 0.85, 0.35, 1] }}
        style={{ display: "flex", flex: 1, minHeight: 0 }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
