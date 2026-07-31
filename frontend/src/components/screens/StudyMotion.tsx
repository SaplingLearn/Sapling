"use client";
import React from "react";
import { motion, MotionGlobalConfig } from "framer-motion";
import { IS_TEST_MODE } from "@/lib/testMode";

// Deterministic DOM for browser tests (#383): framer-motion's own test
// seam jumps every animation straight to its final keyframe. No-op in
// production builds (flag inlined to false at build time).
if (IS_TEST_MODE) MotionGlobalConfig.skipAnimations = true;

/**
 * The Study screen's framer-motion subtree, split out so the library stays
 * out of Study's initial bundle (#111) — Study.tsx loads it
 * via next/dynamic (the MarkdownChat pattern); the mode-switch fade is
 * plain CSS (`study-mode-enter`) so pane content never waits on this chunk.
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
