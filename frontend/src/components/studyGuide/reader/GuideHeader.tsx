"use client";
import { Icon } from "@/components/Icon";
import { SpaceBar } from "@/components/studyGuide/shared/SpaceBar";
import { Chip } from "@/components/ui";
import type { GuideDetail } from "@/lib/studyGuide/types";

import { GuideMenu } from "./GuideMenu";
import s from "./reader.module.css";
import { countdownLabel, DEPTH_LABEL, GOAL_LABEL, sectionBars, sourcesLabel } from "./readerModel";

function GuideChips({ guide, days }: { guide: GuideDetail; days: number | null }) {
  const sources = guide.content.sources.length;
  return (
    <div className={s.chips}>
      <Chip variant="warn" icon={<Icon name="sparkle" size={11} />}>
        AI generated
      </Chip>
      <Chip variant="accent">{GOAL_LABEL[guide.goal]}</Chip>
      <Chip>{DEPTH_LABEL[guide.depth]}</Chip>
      {days !== null && <Chip variant="err">{countdownLabel(guide.content.scope_label, days)}</Chip>}
      {sources > 0 && <span className={s.chipNote}>{sourcesLabel(sources, guide.counts.minutes)}</span>}
    </div>
  );
}

function SpacePanel({ guide }: { guide: GuideDetail }) {
  const bars = sectionBars(guide.content);
  if (bars.length === 0) return null;
  return (
    <div className={s.space}>
      <div className={s.spaceHead}>
        <span className={s.spaceTitle}>How this guide spends its space</span>
        <span className={s.spaceNote}>
          {guide.use_history ? "More room where you are weakest" : "Every section gets the same room"}
        </span>
      </div>
      <SpaceBar bars={bars} legend />
    </div>
  );
}

/** The title and its menu, the deck, the chips, and the space bar. */
export function GuideHeader({
  guide,
  days,
  generating,
  onSave,
  onRegenerate,
}: {
  guide: GuideDetail;
  /** Days to the due date, or null with none ahead. */
  days: number | null;
  generating: boolean;
  onSave: () => void;
  onRegenerate: () => void;
}) {
  const { title, deck } = guide.content;
  return (
    <header className={s.header}>
      <div className={s.titleRow}>
        <h1 className={`h-serif ${s.title}`} data-testid="guide-title">
          {title}
        </h1>
        <GuideMenu saved={guide.saved_at !== null} busy={generating} onSave={onSave} onRegenerate={onRegenerate} />
      </div>
      {deck && <p className={s.deck}>{deck}</p>}
      <GuideChips guide={guide} days={days} />
      <SpacePanel guide={guide} />
    </header>
  );
}
