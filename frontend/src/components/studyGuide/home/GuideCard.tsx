import Link from "next/link";

import { Icon } from "@/components/Icon";
import { Chip } from "@/components/ui";
import type { GuideCard as Guide, GuideCounts } from "@/lib/studyGuide/types";
import { studyGuideReaderHref } from "@/lib/toolHrefs";

import { GoalDepthChips } from "../shared/GoalDepthChips";
import { newLecturesText } from "../shared/labels";
import { SpaceBar, widestBar } from "../shared/SpaceBar";
import { tierLabel, tierText } from "../shared/tiers";
import { dateText, statusText } from "./guidesModel";
import s from "./home.module.css";

const FIGURES: { key: keyof GuideCounts; one: string; many: string }[] = [
  { key: "sections", one: "Section", many: "Sections" },
  { key: "blocks", one: "Block", many: "Blocks" },
  { key: "practice", one: "Practice", many: "Practice" },
  { key: "minutes", one: "Minute", many: "Minutes" },
];

/** One guide on the home. The whole card opens it in the reader. */
export function GuideCard({ guide, now }: { guide: Guide; now: Date }) {
  return (
    <li className={s.cell}>
      <Link
        href={studyGuideReaderHref(guide.id)}
        className={s.card}
        data-testid={`guides-card-${guide.id}`}
        data-status={guide.status}
      >
        <h2 className={`h-serif ${s.title}`}>{guide.title}</h2>
        <Meta guide={guide} now={now} />
        <Room guide={guide} />
        <dl className={s.figures}>
          {FIGURES.map(figure => (
            <div key={figure.key} className={s.figure} data-testid={`guides-card-${figure.key}-${guide.id}`}>
              <dt className="label-micro">{guide.counts[figure.key] === 1 ? figure.one : figure.many}</dt>
              <dd>{guide.counts[figure.key]}</dd>
            </div>
          ))}
        </dl>
        <div className={s.foot}>
          <span className={s.chips}>
            <Chip>{guide.scope_label}</Chip>
            <GoalDepthChips goal={guide.goal} depth={guide.depth} />
          </span>
          <span className={s.course}>{guide.course_name}</span>
        </div>
      </Link>
    </li>
  );
}

/** The date, then what is worth knowing: not finished, new lectures, saved. */
function Meta({ guide, now }: { guide: Guide; now: Date }) {
  const status = statusText(guide.status);
  const lectures = newLecturesText(guide.new_materials);
  return (
    <div className={s.meta}>
      <span>{dateText(guide, now)}</span>
      {status && (
        <span className={guide.status === "failed" ? s.metaFailed : s.metaUnfinished} data-testid={`guides-card-status-${guide.id}`}>
          {status}
        </span>
      )}
      {lectures && <span className={s.metaNew} data-testid={`guides-card-new-${guide.id}`}>{lectures}</span>}
      {guide.saved_at && (
        <span className={s.metaSaved} data-testid={`guides-card-saved-${guide.id}`}>
          <Icon name="check" size={11} /> Saved
        </span>
      )}
    </div>
  );
}

/** The mastery bar and the section it gives the most room to. */
function Room({ guide }: { guide: Guide }) {
  const widest = widestBar(guide.bars);
  return (
    <div className={s.room}>
      <SpaceBar bars={guide.bars} />
      {widest && (
        <span className={s.roomLine} data-testid={`guides-card-room-${guide.id}`}>
          Most room: {widest.title},{" "}
          <span className={s.roomTier} style={{ color: tierText(widest.tier) }}>{tierLabel(widest.tier)}</span>
        </span>
      )}
    </div>
  );
}
