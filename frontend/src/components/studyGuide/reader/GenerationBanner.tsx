import { Button, InlineBanner } from "@/components/ui";
import type { GenerationStep } from "@/lib/studyGuide/types";

import s from "./reader.module.css";

/** The dark strip that follows the page while the guide is being written. */
export function GenerationBanner({ label, step }: { label: string; step: GenerationStep | null }) {
  const percent = step && step.total > 0 ? Math.min(100, Math.round((step.step / step.total) * 100)) : 0;
  return (
    <div role="status" className={s.banner} data-testid="guide-generating">
      <div className={s.bannerRow}>
        <span className={s.spinner} aria-hidden="true" />
        <span className={s.bannerLabel}>{label}</span>
        {step && (
          <span className={s.bannerStep}>
            Step {step.step} of {step.total}
          </span>
        )}
      </div>
      <div className={s.bannerTrack} aria-hidden="true">
        <div className={s.bannerBar} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

/** The generation stopped. Retry picks up at the first section not written. */
export function GenerationError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <InlineBanner
      tone="neutral"
      testid="guide-generation-error"
      actions={
        <Button size="sm" data-testid="guide-generation-retry" onClick={onRetry}>
          Retry
        </Button>
      }
    >
      {message}
    </InlineBanner>
  );
}
