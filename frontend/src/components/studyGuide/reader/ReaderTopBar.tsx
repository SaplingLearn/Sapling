"use client";
import { BackLink } from "@/components/BackLink";
import { AIDisclaimerChip } from "@/components/chat/AIDisclaimerChip";
import { TopBar } from "@/components/TopBar";
import { Toggle } from "@/components/ui";
import { studyHref } from "@/lib/toolHrefs";

import type { ViewMode } from "./readerModel";

const MODES: { value: ViewMode; label: string; title: string }[] = [
  { value: "read", label: "Read", title: "The full guide" },
  { value: "skim", label: "Skim", title: "One line per passage, blocks kept" },
];

export function ReaderTopBar({
  mode,
  onMode,
  courseId,
}: {
  mode: ViewMode;
  onMode: (mode: ViewMode) => void;
  /** The guide's class, once loaded: Back returns to the hub on it. */
  courseId?: string;
}) {
  return (
    <TopBar
      title="Study"
      actions={
        <>
          <div role="group" aria-label="View mode">
            <Toggle testid="guide-mode" options={MODES} value={mode} onChange={onMode} />
          </div>
          <AIDisclaimerChip />
          <BackLink href={studyHref(courseId)} label="Study" />
        </>
      }
    />
  );
}
