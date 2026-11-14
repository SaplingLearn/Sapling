import { Icon } from "@/components/Icon";
import { Skeleton } from "@/components/Skeleton";
import { Button, EmptyState } from "@/components/ui";

import s from "./home.module.css";

/** One card in outline: the same rows at the same heights as a real one. */
function GhostCard() {
  return (
    <li className={s.cell}>
      <div className={`${s.card} ${s.ghost}`}>
        <div className={s.ghostTitle}>
          <Skeleton width="82%" height={20} />
          <Skeleton width="48%" height={20} />
        </div>
        <div className={s.meta}>
          <Skeleton width={118} height={10} />
          <Skeleton width={72} height={10} />
        </div>
        <div className={s.room}>
          <Skeleton height={10} radius="var(--r-xs)" />
          <div className={s.roomRow}><Skeleton width="58%" height={12} /></div>
        </div>
        <div className={s.figures}>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={s.figure}>
              <Skeleton width={26} height={24} />
              <Skeleton width={46} height={12} />
            </div>
          ))}
        </div>
        <div className={s.foot}>
          <span className={s.pills}>
            <Skeleton width={78} height={26} radius={999} />
            <Skeleton width={84} height={26} radius={999} />
          </span>
          <Skeleton width={58} height={14} />
        </div>
      </div>
    </li>
  );
}

/** The grid while the list loads: cards in outline. */
export function GuidesSkeleton() {
  return (
    <ul className={s.grid} aria-busy="true" aria-label="Loading your study guides" data-testid="guides-loading">
      {Array.from({ length: 6 }).map((_, i) => <GhostCard key={i} />)}
    </ul>
  );
}

/** No guide yet: what one is, and the way to the first. On the cards' paper. */
export function GuidesEmpty({ onNew }: { onNew: () => void }) {
  return (
    <div className={s.empty}>
      <EmptyState
        testid="guides-empty"
        title="No study guides yet"
        body="Make one for an exam, an assignment or a whole class. It is written from your own materials and gives the most room to what you have not mastered."
        action={(
          <Button variant="primary" className={s.newGuide} data-testid="guides-empty-new" onClick={onNew}>
            <Icon name="plus" size={14} /> New study guide
          </Button>
        )}
      />
    </div>
  );
}

export function GuidesNoMatch({ query }: { query: string }) {
  return (
    <p className={s.quiet} role="status" data-testid="guides-no-match">
      No guide matches &ldquo;{query.trim()}&rdquo;.
    </p>
  );
}

/** A failed load is not an empty list: say so, and offer the load again. */
export function GuidesLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className={s.loadError} role="alert" data-testid="guides-load-error">
      <div className={`h-serif ${s.loadErrorTitle}`}>Couldn&apos;t load your study guides</div>
      <p>Your guides are safe. Check your connection and try again.</p>
      <Button variant="primary" data-testid="guides-load-retry" onClick={onRetry}>Try again</Button>
    </div>
  );
}
