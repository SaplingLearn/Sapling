"use client";
/**
 * The retention check lives on Study (RETENTION_NAV_HREF), and `hide_study`
 * (#620) can hide Study: its nav row goes, and NavFeatureGate sends its routes
 * to /dashboard. Anything that points the student at the check — the mobile
 * menu's dot, the Dashboard's card — reads the due state through here, so it
 * never points at a page the student cannot open.
 */
import { useMemo } from "react";

import { useRetentionDue, type RetentionDueState } from "@/context/RetentionDueContext";
import { useVisibleNavSections } from "@/lib/useNavSections";
import { RETENTION_NAV_HREF } from "./RetentionDueDot";

/** Study is a destination this student can open. False while the flags are
 *  still loading (the nav holds flagged rows back until then, too). */
export function useStudyNavShown(): boolean {
  const sections = useVisibleNavSections();
  return sections.some((section) => section.items.some((item) => item.href === RETENTION_NAV_HREF));
}

/** The shell's retention-due state, or nothing due while Study is hidden. */
export function useRetentionNavDue(): RetentionDueState {
  const state = useRetentionDue();
  const shown = useStudyNavShown();
  return useMemo(
    () => (shown ? state : { ...state, due: false, courseIds: [] }),
    [shown, state],
  );
}
