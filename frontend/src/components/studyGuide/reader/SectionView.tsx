"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import { Skeleton, SkeletonText } from "@/components/Skeleton";
import { Button } from "@/components/ui";
import type { Item, Section } from "@/lib/studyGuide/types";

import { BlockView } from "./blocks/BlockView";
import { Prose } from "./Prose";
import s from "./reader.module.css";
import { useReader } from "./ReaderContext";
import { sectionAnchor, sectionNumber, type SectionPhase } from "./readerModel";
import { ReadMark } from "./ReadMark";

function SectionItems({ items, hidden = false }: { items: Item[]; hidden?: boolean }) {
  return (
    <div className={`${s.sectionBody} fade-in`} hidden={hidden}>
      {items.map(item =>
        item.type === "prose" ? <Prose key={item.id} item={item} /> : <BlockView key={item.id} block={item} />,
      )}
    </div>
  );
}

/** A section the student has mastered: one line, with the rest a click away. */
function MasteredSection({ section }: { section: Section }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <div className={s.mastered}>
        <span className={s.masteredIcon} aria-hidden="true">
          <Icon name="leaf" size={16} />
        </span>
        <div className={s.masteredText}>
          <strong>You have mastered this, so it gets one line.</strong>
          <span className={s.oneLine}>{section.one_line}</span>
        </div>
        <button
          type="button"
          className={s.expand}
          data-testid={`guide-section-expand-${section.id}`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? "Hide full section" : "Show full section"}
        </button>
      </div>
      {/* Kept in the page while closed, so a printout has the whole section. */}
      <SectionItems items={section.items} hidden={!open} />
    </>
  );
}

function SectionWaiting({ writing }: { writing: boolean }) {
  return (
    <div className={s.waiting}>
      <span className={s.waitingLabel}>{writing ? "Writing this section" : "Queued"}</span>
      <SkeletonText lines={3} lineHeight={14} gap={12} lastWidth="70%" />
      <Skeleton height={writing ? 220 : 120} radius="var(--r-lg)" />
    </div>
  );
}

/** A section the writer gave up on. Try again writes what the guide is missing. */
function SectionFailed({ sectionId, onRetry }: { sectionId: string; onRetry: () => void }) {
  const { generating } = useReader();
  return (
    <div className={s.failed}>
      <p className={s.note}>This section could not be written.</p>
      <Button size="sm" data-testid={`guide-section-retry-${sectionId}`} disabled={generating} onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function SectionBody({ section, phase, onRetry }: { section: Section; phase: SectionPhase; onRetry: () => void }) {
  if (phase === "failed") return <SectionFailed sectionId={section.id} onRetry={onRetry} />;
  if (phase !== "written") return <SectionWaiting writing={phase === "writing"} />;
  if (section.tier === "mastered") return <MasteredSection section={section} />;
  return <SectionItems items={section.items} />;
}

export function SectionView({
  section,
  index,
  phase,
  read,
  onToggleRead,
  onRetry,
}: {
  section: Section;
  index: number;
  phase: SectionPhase;
  read: boolean;
  onToggleRead: () => void;
  /** Runs the generation that writes a section that failed. */
  onRetry: () => void;
}) {
  const anchor = sectionAnchor(section.id);
  return (
    <section id={anchor} data-testid={anchor} className={s.section} aria-labelledby={`${anchor}-title`}>
      <div className={s.sectionHead}>
        <div className={s.sectionTitle}>
          <span className={s.sectionNumber}>{sectionNumber(index)}</span>
          <h2 id={`${anchor}-title`}>{section.title}</h2>
        </div>
        <button
          type="button"
          className={s.readToggle}
          data-testid={`guide-section-read-${section.id}`}
          aria-pressed={read}
          disabled={phase !== "written"}
          onClick={onToggleRead}
        >
          <ReadMark read={read} />
          {read ? "Read" : "Mark as read"}
        </button>
      </div>
      <SectionBody section={section} phase={phase} onRetry={onRetry} />
    </section>
  );
}
