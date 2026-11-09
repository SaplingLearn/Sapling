"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useFlagMap } from "@/context/FlagsContext";
import { libraryHref, flashcardsHref } from "@/lib/toolHrefs";

const StudyHighlight = dynamic(
  () => import("./screens/StudyMotion").then(module => module.StudyToggleHighlight),
  { ssr: false, loading: () => <span aria-hidden style={{ position: "absolute", inset: 0, borderRadius: "inherit", background: "var(--accent-soft)", zIndex: -1 }} /> },
);

type StudyMode = "guide" | "cards" | "quiz";

/**
 * The Study tool nav. Each tab is a page of its own now — the in-place
 * `onChange` switch is gone with the tabbed Study screen that owned it, so
 * these are plain links (which also makes middle-click and Open-in-new-tab
 * behave, where the old handler only stepped aside for modifier clicks).
 */
export function StudyTabs({ mode }: { mode: StudyMode }) {
  const { flags, ready } = useFlagMap();
  const tabs = [
    { mode: "guide", label: "Study Guide", href: libraryHref(null, "study_guide") },
    { mode: "cards", label: "Flashcards", href: flashcardsHref() },
    { mode: "quiz", label: "Quiz", href: "/quiz" },
  ] as const;

  return (
    <nav className="study-tabs" aria-label="Study tools">
      {tabs.filter(tab => tab.mode !== "quiz" || (ready && flags.hide_quiz !== "on")).map(tab => (
        <Link key={tab.mode} href={tab.href} aria-current={mode === tab.mode ? "page" : undefined}>
          {mode === tab.mode && <StudyHighlight />}
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
