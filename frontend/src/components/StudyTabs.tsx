"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useFlagMap } from "@/context/FlagsContext";

const StudyHighlight = dynamic(
  () => import("./screens/StudyMotion").then(module => module.StudyToggleHighlight),
  { ssr: false, loading: () => <span aria-hidden style={{ position: "absolute", inset: 0, borderRadius: "inherit", background: "var(--accent-soft)", zIndex: -1 }} /> },
);

type StudyMode = "guide" | "cards" | "quiz";

export function StudyTabs({ mode, onChange }: { mode: StudyMode; onChange?: (mode: "guide" | "cards") => void }) {
  const { flags, ready } = useFlagMap();
  const tabs = [
    { mode: "guide", label: "Study Guide", href: "/study?mode=guide" },
    { mode: "cards", label: "Flashcards", href: "/study?mode=cards" },
    { mode: "quiz", label: "Quiz", href: "/quiz" },
  ] as const;

  return (
    <nav className="study-tabs" aria-label="Study tools">
      {tabs.filter(tab => tab.mode !== "quiz" || (ready && flags.hide_quiz !== "on")).map(tab => (
        <Link
          key={tab.mode}
          href={tab.href}
          aria-current={mode === tab.mode ? "page" : undefined}
          onClick={event => {
            if (onChange && tab.mode !== "quiz" && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
              event.preventDefault();
              onChange(tab.mode);
            }
          }}
        >
          {mode === tab.mode && <StudyHighlight />}
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
