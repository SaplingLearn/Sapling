"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { adminListFlags, adminUpdateFlag } from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * The waitlist gate on the Allowlist tab: whether `open_access` is on, and a
 * switch for it (docs/design/open-access-gate.md). It edits the flag's
 * default, exactly as the Feature flags tab would. Turning it on lets anyone
 * who signs in use Sapling, without approving them; turning it off puts those
 * people back on the waitlist. Approvals are never touched either way.
 *
 * `SAPLING_FLAG_OPEN_ACCESS` on the server wins over the stored default, so
 * when it is set the banner shows the FORCED state and hides the switch
 * (flipping the stored default would change nothing). `onChanged` reports
 * the effective state, or null when it could not be read.
 */
export const OPEN_ACCESS_FLAG = "open_access";

export function OpenAccessBanner({ onChanged }: { onChanged?: (open: boolean | null) => void }) {
  const toast = useToast();
  // null = not read (yet, or the read failed): the switch stays hidden rather
  // than guessing the state. `open` is the STORED default; `forced` the
  // variant the env override pins, which wins over it.
  const [open, setOpen] = React.useState<boolean | null>(null);
  const [forced, setForced] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    adminListFlags().then(
      (r) => {
        if (!live) return;
        const flag = r.flags.find((f) => f.key === OPEN_ACCESS_FLAG);
        const isOpen = flag?.default_variant === "on";
        const env = flag?.env_override ?? null;
        setOpen(flag ? isOpen : null);
        setForced(env);
        onChanged?.(flag ? (env ? env === "on" : isOpen) : null);
      },
      () => {
        if (!live) return;
        setOpen(null);
        onChanged?.(null);
      },
    );
    return () => { live = false; };
  }, [onChanged]);

  if (open === null) return null;
  // What sign-in actually does right now.
  const effective = forced ? forced === "on" : open;

  const flip = async () => {
    const next = !open;
    setSaving(true);
    try {
      await adminUpdateFlag(OPEN_ACCESS_FLAG, { default_variant: next ? "on" : "off" });
      setOpen(next);
      onChanged?.(next);
      setConfirming(false);
      toast.success(next
        ? "Open access is on. Anyone who signs in can use Sapling."
        : "Open access is off. People who joined through it are back on the waitlist.");
    } catch (err) {
      toast.error(`Could not change open access: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div
        role="status"
        data-testid="open-access-banner"
        data-open={effective ? "true" : "false"}
        data-forced={forced ? "true" : "false"}
        className={cn("flex flex-wrap items-center gap-3 mb-4 py-2.5 px-3.5 rounded-sm text-md", effective ? "bg-warn-soft" : "bg-bg-soft", effective ? "text-warn" : "text-text-dim", effective ? "border border-transparent" : "border border-border")}
      >
        <span className="flex-1 min-w-55">
          {effective ? (
            <><strong>Open access is on.</strong> Anyone who signs in gets in without approval. They show here as
              “open access” and go back to waiting when {forced ? "it is turned off" : "you turn this off"}.</>
          ) : (
            <><strong>Waitlist required.</strong> Only approved addresses can sign in.</>
          )}
          {forced && (
            <span data-testid="open-access-forced" className="block mt-1">
              Set by <code>SAPLING_FLAG_OPEN_ACCESS={forced}</code> on the server, which overrides this switch.
              Remove that variable to control it here.
            </span>
          )}
        </span>
        {!forced && (
          <button
            type="button"
            data-testid="open-access-toggle"
            className={`btn btn--sm ${open ? "" : "btn--ghost"}`}
            onClick={() => setConfirming(true)}
          >
            {open ? "Require the waitlist" : "Open access"}
          </button>
        )}
      </div>

      <Dialog
        open={confirming}
        onClose={() => { if (!saving) setConfirming(false); }}
        size="sm"
        title={open ? "Require the waitlist again?" : "Open access to everyone?"}
      >
        <p className="flags__confirm-text mb-5" data-testid="open-access-confirm-text">
          {open
            ? "People who joined through open access lose access within a minute and are back on the waitlist. Approved people are not affected. You can approve anyone to keep them in."
            : "Anyone with a Google account, BU or not, can sign in and use Sapling without approval. They are added to this list unapproved. Accounts you removed stay out."}
        </p>
        <div className="flags__confirm-actions">
          <button type="button" className="btn" disabled={saving} onClick={() => setConfirming(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="open-access-confirm"
            disabled={saving}
            onClick={() => void flip()}
          >
            {saving ? "Saving…" : open ? "Require the waitlist" : "Open access"}
          </button>
        </div>
      </Dialog>
    </>
  );
}
