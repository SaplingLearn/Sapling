"use client";
import { tierFill, tierLabel, tierText } from "@/components/studyGuide/shared/tiers";
import type { GuideDetail, Section } from "@/lib/studyGuide/types";

import { liveTier, PHASE_LABEL, sectionAnchor, type SectionPhase } from "../readerModel";
import { ReadMark } from "../ReadMark";
import s from "./rail.module.css";

/** The section's mastery now, or where its writing stands while the guide is generated. */
function Status({ section, phase, guide, generating }: { section: Section; phase: SectionPhase; guide: GuideDetail; generating: boolean }) {
  if (generating || phase !== "written") {
    return (
      <span className={s.outlineStatus}>
        <span className={phase === "writing" ? `${s.dot} ${s.dotWriting}` : s.dot} aria-hidden="true" />
        {PHASE_LABEL[phase]}
      </span>
    );
  }
  const tier = liveTier(section, guide.mastery);
  return (
    <span className={s.outlineStatus} style={{ color: tierText(tier) }}>
      <span className={s.dot} style={{ background: tierFill(tier) }} aria-hidden="true" />
      {tierLabel(tier)}
      {section.tier === "mastered" && ", one line"}
    </span>
  );
}

/** "In this guide": each section with its read mark, a link to it and its mastery. */
export function Outline({
  guide,
  phases,
  generating,
  onToggleRead,
}: {
  guide: GuideDetail;
  phases: Record<string, SectionPhase>;
  generating: boolean;
  onToggleRead: (sectionId: string) => void;
}) {
  return (
    <nav aria-label="In this guide" className={s.outline}>
      <span className="label-micro">In this guide</span>
      <ul className={s.outlineList}>
        {guide.content.sections.map(section => {
          const read = guide.read_sections.includes(section.id);
          const phase = phases[section.id];
          return (
            <li key={section.id}>
              <button
                type="button"
                className={s.outlineRead}
                data-testid={`guide-outline-read-${section.id}`}
                aria-pressed={read}
                aria-label={`${read ? "Mark unread" : "Mark as read"}: ${section.title}`}
                disabled={phase !== "written"}
                onClick={() => onToggleRead(section.id)}
              >
                <ReadMark read={read} />
              </button>
              <a href={`#${sectionAnchor(section.id)}`} className={s.outlineLink} data-testid={`guide-outline-${section.id}`}>
                <span className={s.outlineTitle}>{section.title}</span>
                <Status section={section} phase={phase} guide={guide} generating={generating} />
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
