"use client";
import { Icon } from "@/components/Icon";

import { staleLabel } from "../readerModel";
import s from "./rail.module.css";

/** Lectures arrived after the guide was made. Update folds them in. */
export function StaleBanner({ count, busy, onUpdate }: { count: number; busy: boolean; onUpdate: () => void }) {
  return (
    <div role="status" className={s.stale} data-testid="guide-stale">
      <strong className={s.noticeTitle}>
        <Icon name="error" size={15} />
        {staleLabel(count)}
      </strong>
      <span>Updating keeps your edits and adds what changed.</span>
      <button type="button" className={`btn ${s.updateButton}`} data-testid="guide-update" disabled={busy} onClick={onUpdate}>
        Update guide
      </button>
    </div>
  );
}

/** An Update finished during this visit. */
export function UpdatedNotice() {
  return (
    <div role="status" className={s.updated} data-testid="guide-updated">
      <strong className={s.noticeTitle}>
        <Icon name="check" size={13} />
        Guide is up to date
      </strong>
      <span>What changed was added. Your read marks were kept, and so was the earlier version.</span>
    </div>
  );
}
