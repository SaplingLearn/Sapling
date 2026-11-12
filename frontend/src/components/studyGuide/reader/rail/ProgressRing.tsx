import { Chip } from "@/components/ui";

import { daysLeftLabel, plural, progressTitle } from "../readerModel";
import s from "./rail.module.css";

const RADIUS = 31;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** How much of the guide has been marked read, and what it is for. */
export function ProgressRing({
  read,
  total,
  scopeLabel,
  dueLabel,
  days,
}: {
  read: number;
  total: number;
  scopeLabel: string;
  /** "Wed, Nov 18", or "" with no date. */
  dueLabel: string;
  /** Days to the due date, or null with none ahead. */
  days: number | null;
}) {
  const filled = total > 0 ? (CIRCUMFERENCE * read) / total : 0;
  return (
    <div className={s.progress} data-testid="guide-progress">
      <svg role="img" aria-label={`${read} of ${plural(total, "section")} read`} width="76" height="76" viewBox="0 0 76 76">
        <circle cx="38" cy="38" r={RADIUS} className={s.ringTrack} />
        <circle
          cx="38"
          cy="38"
          r={RADIUS}
          className={s.ringFill}
          strokeDasharray={`${filled.toFixed(1)} ${CIRCUMFERENCE.toFixed(1)}`}
          transform="rotate(-90 38 38)"
        />
        <text x="38" y="44" textAnchor="middle" className={s.ringText}>
          {read}/{total}
        </text>
      </svg>
      <div className={s.progressText}>
        <span className={s.progressTitle}>{progressTitle(read, total)}</span>
        <span className={s.progressScope}>{[scopeLabel, dueLabel].filter(Boolean).join(" · ")}</span>
        {days !== null && <Chip variant="err">{daysLeftLabel(days)}</Chip>}
      </div>
    </div>
  );
}
