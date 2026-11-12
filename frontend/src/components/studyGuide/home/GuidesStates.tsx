import { Skeleton } from "@/components/Skeleton";
import { Button, EmptyState } from "@/components/ui";

import s from "./home.module.css";

/** The grid while the list loads: cards in outline. */
export function GuidesSkeleton() {
  return (
    <ul className={s.grid} aria-busy="true" aria-label="Loading your study guides" data-testid="guides-loading">
      {Array.from({ length: 6 }).map((_, i) => (
        <li key={i} className={s.cell}>
          <div className={s.ghost}>
            <Skeleton width="78%" height={20} />
            <Skeleton width="45%" height={11} />
            <Skeleton height={12} radius="var(--r-xs)" />
            <Skeleton width="60%" height={11} />
            <Skeleton height={34} />
            <Skeleton width="70%" height={20} radius={999} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** No guide yet: what one is, and the way to the first. */
export function GuidesEmpty({ onNew }: { onNew: () => void }) {
  return (
    <EmptyState
      testid="guides-empty"
      title="No study guides yet"
      body="Make one for an exam, an assignment or a whole class. It is written from your own materials and gives the most room to what you have not mastered."
      action={<Button variant="primary" data-testid="guides-empty-new" onClick={onNew}>New study guide</Button>}
    />
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
