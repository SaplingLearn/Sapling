"use client";
import React from "react";
import { Sheet } from "@/components/ui/Sheet";
import { useIsMobile } from "@/lib/useIsMobile";

/* Secondary context (learning route, selected material, goal/plan, map):
 * a rail beside the main column on desktop, ONE labelled sheet on a phone.
 * The content is mounted in exactly one place at a time, so ids and live
 * state are never duplicated. All modal behaviour — portal, focus moved
 * inside, Tab trap, Escape, focus returned to the opener, background scroll
 * lock — is ui/Sheet's (Dialog's useOverlayBehaviour), not re-implemented. */

export interface ContextSheetProps {
  open: boolean;
  onClose: () => void;
  /** Visible heading and accessible name of the dialog. */
  title: string;
  children: React.ReactNode;
  /** Phone default; "right" suits a tablet/desktop drawer. */
  side?: "bottom" | "right";
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  /** Extra class on the sheet backdrop, appended to the sapling scope classes
   *  (e.g. a screen's full-height variant). Optional; omitting it changes nothing. */
  className?: string;
  testid?: string;
}

export function ContextSheet({ open, onClose, title, children, side = "bottom", initialFocusRef, className, testid }: ContextSheetProps) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      side={side}
      width={side === "right" ? 420 : undefined}
      className={className ? `sapling-surface sapling-context-sheet ${className}` : "sapling-surface sapling-context-sheet"}
      initialFocusRef={initialFocusRef}
      testid={testid}
    >
      {children}
    </Sheet>
  );
}

export interface ContextPanelProps {
  /** Names the rail (`aside`) and titles the phone sheet. */
  label: string;
  /** Phone trigger text; defaults to the label. */
  triggerLabel?: string;
  children: React.ReactNode;
  /** Controlled phone-sheet state (e.g. Library opens it when a row is
   *  selected). Leave both unset for a self-managed trigger. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Hide the built-in phone trigger when the caller opens the sheet itself. */
  hideTrigger?: boolean;
  /** Below this width the panel becomes a sheet. Defaults to useIsMobile's 768. */
  breakpoint?: number;
  /** Extra class for the phone sheet (passed to ContextSheet's `className`). */
  sheetClassName?: string;
  testid?: string;
}

export function ContextPanel({
  label,
  triggerLabel,
  children,
  open: openProp,
  onOpenChange,
  hideTrigger = false,
  breakpoint,
  sheetClassName,
  testid,
}: ContextPanelProps) {
  const isPhone = useIsMobile(breakpoint);
  const [openState, setOpenState] = React.useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : openState;
  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!controlled) setOpenState(next);
      onOpenChange?.(next);
    },
    [controlled, onOpenChange],
  );

  if (!isPhone) {
    return (
      <aside className="sapling-context-rail" aria-label={label} data-testid={testid}>
        {children}
      </aside>
    );
  }

  return (
    <>
      {!hideTrigger && (
        <button
          type="button"
          className="sapling-context-trigger"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen(true)}
          data-testid={testid ? `${testid}-trigger` : undefined}
        >
          {triggerLabel ?? label}
        </button>
      )}
      <ContextSheet open={open} onClose={() => setOpen(false)} title={label} className={sheetClassName} testid={testid}>
        {children}
      </ContextSheet>
    </>
  );
}
