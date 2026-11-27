"use client";
/**
 * Where the hub's links go, and how it leaves.
 *
 * Two depths, on purpose.
 *   The header's tool buttons open the TOOL: its own home, with nothing
 *   started. That is where you browse decks, pick what to quiz or find a
 *   guide. Quiz and Flashcards open on this course; Study Guide opens the
 *   Study Guides home, which lists every class's guides.
 *   A concept's "..." menu, the Up Next block and Quick Reviews go straight
 *   INTO it: the quiz starts on that concept, flashcards open on its deck
 *   (`start=1`).
 * The hub owns "which course"; Quiz and Flashcards open on it and come back
 * to it. Study Guide is not offered per concept: a guide covers an exam, an
 * assignment or the whole course, so it is reached from the header only.
 */
import React from "react";
import { useRouter } from "next/navigation";
import { handoffLearnHref } from "@/lib/learningHandoffs";
import { buildQuizHref } from "@/lib/quiz/source";
import { MOTION } from "@/lib/designTokens";
import { flashcardsHref, studyGuideHref, studyHref } from "@/lib/toolHrefs";

export type ToolKey = "quiz" | "cards" | "guide";

const TOOL_HOME: Record<ToolKey, (courseId: string) => string> = {
  // W7.D2: header Quiz → course home/launcher (no start=1); see docs/learning-loop/w7-d2-hub-guide-settings.md
  quiz: cid => buildQuizHref({ course: cid }, { kind: "link", returnTo: studyHref(cid) }),
  cards: cid => flashcardsHref(cid),
  guide: () => studyGuideHref(),
};

/** How long the hub's fade-out runs before the route changes: `.leaving`'s
 *  --dur-fast, an exit's duration (MOTION mirrors the CSS token). */
const LEAVE_MS = Math.round(MOTION.duration.fast * 1000);

export interface ToolNav {
  /** True while the hub fades out on its way to a tool. */
  leaving: boolean;
  /** Fades the hub out, then navigates (at once under reduced motion). */
  leaveTo: (href: string) => void;
  /** A tool's home: Quiz and Flashcards on this course, the Study Guides home. */
  toolHome: (tool: ToolKey) => string;
  /** A quiz started on one concept, returning to this course. */
  quizHref: (conceptId: string) => string;
  /** Flashcards started on these concepts' decks. */
  cardsHref: (conceptNames: string[]) => string;
  /** Tutor session on one concept (W3.4 Continue learning). */
  learnHref: (conceptId: string, conceptName: string) => string;
}

export function useToolNav(courseId: string): ToolNav {
  const router = useRouter();
  // Leaving for a tool fades the hub out first, so the tool's arrival
  // (`tool-enter`) reads as one hand-off rather than a cut.
  const [leaving, setLeaving] = React.useState(false);
  const leaveTo = React.useCallback((href: string) => {
    const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { router.push(href); return; }
    setLeaving(true);
    window.setTimeout(() => router.push(href), LEAVE_MS);
  }, [router]);

  return React.useMemo(() => ({
    leaving,
    leaveTo,
    toolHome: tool => TOOL_HOME[tool](courseId),
    quizHref: conceptId =>
      buildQuizHref({ concept: conceptId }, { kind: "link", returnTo: studyHref(courseId) }, { start: true }),
    cardsHref: names => flashcardsHref(courseId, names, { start: true }),
    learnHref: (conceptId, conceptName) =>
      handoffLearnHref({ conceptId, conceptName, courseId }),
  }), [leaving, leaveTo, courseId]);
}

// A real link that leaves through the hub's fade is a HandoffLink with
// `onNavigate={nav.leaveTo}` (components/ui/HandoffLink.tsx).
