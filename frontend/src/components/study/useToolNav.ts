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
import { buildQuizHref } from "@/lib/quiz/source";
import { flashcardsHref, studyGuideHref, studyHref } from "@/lib/toolHrefs";

export type ToolKey = "quiz" | "cards" | "guide";

const TOOL_HOME: Record<ToolKey, (courseId: string) => string> = {
  quiz: cid => buildQuizHref({ course: cid }, { kind: "link", returnTo: studyHref(cid) }),
  cards: cid => flashcardsHref(cid),
  guide: () => studyGuideHref(),
};

/** How long the hub's fade-out runs before the route changes (`.leaving`). */
const LEAVE_MS = 180;

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
  }), [leaving, leaveTo, courseId]);
}

/**
 * onClick for a real link that should leave through the hub's fade: a plain
 * click fades and navigates, a Cmd/Ctrl-click is left to the browser (new tab).
 */
export const leaveOnClick = (leaveTo: (href: string) => void, href: string) => (e: React.MouseEvent) => {
  if (e.metaKey || e.ctrlKey) return;
  e.preventDefault();
  leaveTo(href);
};
