"use client";
import React, { useState } from "react";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";

/**
 * Fades its content in when `changeKey` changes: the Tutor's page (home, a
 * course, all sessions, the session) and the session's step (Check-in → Plan
 * → Learn → Wrap-up; the phases within one step share it, so the conversation
 * is never remounted between a turn, a check and its feedback). The key it first renders with is not animated, so the
 * screen's first paint stays still (motion marks a change). A new key remounts
 * the content, as the swap it marks already does; there is no exit, so the old
 * content never lingers beside the new.
 */
export function ChangeFade({ changeKey, className, children }: { changeKey: string; className?: string; children: React.ReactNode }) {
  const m = useMotionPresets();
  const [firstKey] = useState(changeKey);
  return (
    <motion.div key={changeKey} className={className} initial={changeKey === firstKey ? false : m.fade.initial}
      animate={m.fade.animate} transition={m.fade.transition}>
      {children}
    </motion.div>
  );
}
