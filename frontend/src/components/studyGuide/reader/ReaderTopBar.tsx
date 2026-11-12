"use client";
import { BackLink } from "@/components/BackLink";
import { AIDisclaimerChip } from "@/components/chat/AIDisclaimerChip";
import { TopBar } from "@/components/TopBar";
import { Toggle } from "@/components/ui";
import { studyGuideHref } from "@/lib/toolHrefs";

import type { ViewMode } from "./readerModel";

const MODES: { value: ViewMode; label: string; title: string }[] = [
  { value: "read", label: "Read", title: "The full guide" },
  { value: "skim", label: "Skim", title: "One line per passage, blocks kept" },
];

/** The reader is one level inside the tool, so Back goes to the tool's home. */
export function ReaderTopBar({ mode, onMode }: { mode: ViewMode; onMode: (mode: ViewMode) => void }) {
  return (
    <TopBar
      title="Study"
      actions={
        <>
          <div role="group" aria-label="View mode">
            <Toggle testid="guide-mode" options={MODES} value={mode} onChange={onMode} />
          </div>
          <AIDisclaimerChip />
          <BackLink href={studyGuideHref()} label="Study Guides" />
        </>
      }
    />
  );
}
