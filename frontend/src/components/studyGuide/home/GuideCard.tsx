import Link from "next/link";

import { Icon } from "@/components/Icon";
import type { GuideCard as Guide, GuideCounts } from "@/lib/studyGuide/types";
import { studyGuideReaderHref } from "@/lib/toolHrefs";

import { ClassTag } from "../shared/ClassTag";
import { focusLabel, newLecturesText } from "../shared/labels";
import { Pill } from "../shared/Pill";
import { ReadOut } from "../shared/ReadOut";
import { SpaceBar, widestBar } from "../shared/SpaceBar";
import { TierLabel, TierSwatch } from "../shared/TierMarks";
import { dateText, statusText } from "./guidesModel";
import s from "./home.module.css";

const FIGURES: { key: keyof GuideCounts; one: string; many: string }[] = [
  { key: "sections", one: "Section", many: "Sections" },
  { key: "blocks", one: "Block", many: "Blocks" },
  { key: "practice", one: "Practice", many: "Practice" },
  { key: "minutes", one: "Minute", many: "Minutes" },
];

/**
 * One guide on the home. The whole card opens it in the reader. Every card
 * has the same rows at the same heights, so a row of cards lines up.
 */
export function GuideCard({
  guide, now, color,
}: {
  guide: Guide;
  now: Date;
  /** The class's colour (`classColor`). */
  color: string;
}) {
  return (
    <li className={s.cell}>
      <Link
        href={studyGuideReaderHref(guide.id)}
        className={s.card}
        data-testid={`guides-card-${guide.id}`}
        data-status={guide.status}
      >
        <h2 className={s.title} title={guide.title}>{guide.title}</h2>
        <Meta guide={guide} now={now} />
        <Room guide={guide} />
        <Figures guide={guide} />
        <div className={s.foot}>
          <span className={s.pills}>
            <Pill>{guide.scope_label}</Pill>
            <Pill>{focusLabel(guide.goal, guide.depth)}</Pill>
          </span>
          <ClassTag code={guide.course_code} name={guide.course_name} color={color} />
        </div>
      </Link>
    </li>
  );
}

/** The date and what is new since on the left, whether it is saved on the right. */
function Meta({ guide, now }: { guide: Guide; now: Date }) {
  return (
    <div className={s.meta}>
      <span className={s.when}>
        {dateText(guide, now)}
        <Note guide={guide} />
      </span>
      <Saved guide={guide} />
    </div>
  );
}

/** After the date: that the guide is not finished, or else the lectures added since. */
function Note({ guide }: { guide: Guide }) {
  const status = statusText(guide.status);
  const text = status || newLecturesText(guide.new_materials);
  if (!text) return null;
  return (
    <>
      <span aria-hidden="true"> · </span>
      <span className={s.note} data-testid={`guides-card-${status ? "status" : "new"}-${guide.id}`}>{text}</span>
    </>
  );
}

function Saved({ guide }: { guide: Guide }) {
  if (!guide.saved_at) {
    return (
      <span className={s.saved} data-testid={`guides-card-unsaved-${guide.id}`}>
        <Icon name="library" size={13} />Not saved
      </span>
    );
  }
  return (
    <span className={`${s.saved} ${s.savedOn}`} data-testid={`guides-card-saved-${guide.id}`}>
      <Icon name="library" size={13} /><ReadOut>Saved: </ReadOut>In Library
    </span>
  );
}

/** The mastery bar and the section it gives the most room to. */
function Room({ guide }: { guide: Guide }) {
  const widest = widestBar(guide.bars);
  return (
    <div className={s.room}>
      {/* A guide with no section yet keeps the bar's place. */}
      {widest ? <SpaceBar bars={guide.bars} /> : <span className={s.noBar} aria-hidden="true" />}
      <div className={s.roomRow} data-testid={widest ? `guides-card-room-${guide.id}` : undefined}>
        {widest && (
          <>
            <TierSwatch tier={widest.tier} />
            <span className={s.roomText}>Most room: <strong>{widest.title}</strong></span>
            <TierLabel tier={widest.tier} />
          </>
        )}
      </div>
    </div>
  );
}

/** Four numbers over their mono labels. */
function Figures({ guide }: { guide: Guide }) {
  return (
    <dl className={s.figures}>
      {FIGURES.map(figure => (
        <div key={figure.key} className={s.figure} data-testid={`guides-card-${figure.key}-${guide.id}`}>
          <dt className="label-micro">{guide.counts[figure.key] === 1 ? figure.one : figure.many}</dt>
          <dd>{guide.counts[figure.key]}</dd>
        </div>
      ))}
    </dl>
  );
}
