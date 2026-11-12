"use client";
import { useReader } from "../ReaderContext";
import { dueDateLabel, readCount, type SectionPhase } from "../readerModel";
import { AskBox } from "./AskBox";
import { Outline } from "./Outline";
import { ProgressRing } from "./ProgressRing";
import s from "./rail.module.css";
import { StaleBanner, UpdatedNotice } from "./StaleBanner";

/** The column beside the guide: progress, freshness, the outline and the ask box. */
export function Rail({
  phases,
  days,
  updated,
  onToggleRead,
  onUpdate,
}: {
  phases: Record<string, SectionPhase>;
  /** Days to the due date, or null with none ahead. */
  days: number | null;
  /** An Update finished during this visit. */
  updated: boolean;
  onToggleRead: (sectionId: string) => void;
  onUpdate: () => void;
}) {
  const { guide, generating } = useReader();
  return (
    <aside aria-label="Guide details" className={s.rail}>
      <ProgressRing
        read={readCount(guide)}
        total={guide.content.sections.length}
        scopeLabel={guide.content.scope_label}
        dueLabel={dueDateLabel(guide.due_date)}
        days={days}
      />
      {guide.new_materials > 0 && <StaleBanner count={guide.new_materials} busy={generating} onUpdate={onUpdate} />}
      {guide.new_materials === 0 && updated && <UpdatedNotice />}
      <Outline guide={guide} phases={phases} generating={generating} onToggleRead={onToggleRead} />
      <AskBox />
      <p className={s.note}>
        Written by AI from your course materials. Check anything that looks off against the cited source.
      </p>
    </aside>
  );
}
