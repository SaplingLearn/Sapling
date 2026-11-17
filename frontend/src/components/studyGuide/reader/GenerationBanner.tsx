import { Button, InlineBanner } from "@/components/ui";
import type { GenerationStep } from "@/lib/studyGuide/types";

import s from "./reader.module.css";

/** The strip that follows the page while the guide is being written. */
export function GenerationBanner({ label, step }: { label: string; step: GenerationStep | null }) {
  const percent = step && step.total > 0 ? Math.min(100, Math.round((step.step / step.total) * 100)) : 0;
  return (
    <div role="status" className={s.banner} data-testid="guide-generating">
      <div className={s.bannerRow}>
        <span className={s.spinner} aria-hidden="true" />
        <span className={`${s.bannerLabel} ${s.shimmerText}`}>{label}</span>
      </div>
      {/* The label already says which section is being written, so the bar
          carries the overall progress on its own. */}
      <div
        className={s.bannerTrack}
        role="progressbar"
        aria-label="Guide progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        data-testid="guide-generating-bar"
      >
        <div className={s.bannerBar} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

/**
 * A generation stopped, or was turned away. Retry is there when asking again
 * can help; Dismiss when the guide under the banner is whole without it.
 */
export function GenerationError({
  message,
  onRetry,
  onDismiss,
  busy,
}: {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  /** Something else is being written: Retry waits for it. */
  busy: boolean;
}) {
  return (
    <InlineBanner
      tone="neutral"
      testid="guide-generation-error"
      actions={
        <>
          {onRetry && (
            <Button size="sm" data-testid="guide-generation-retry" disabled={busy} onClick={onRetry}>
              Retry
            </Button>
          )}
          {onDismiss && (
            <Button size="sm" variant="ghost" data-testid="guide-generation-dismiss" onClick={onDismiss}>
              Dismiss
            </Button>
          )}
        </>
      }
    >
      {message}
    </InlineBanner>
  );
}
