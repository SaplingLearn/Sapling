"use client";
import React from "react";
import { createPortal } from "react-dom";
import { useOverlayBehaviour } from "@/components/Dialog";
import { Icon } from "@/components/Icon";

/**
 * Sheet — a panel that opens OVER the page, anchored right (#537).
 *
 * The quiz's "Ask about this" needs the question to stay visible while the
 * tutor answers, which nothing in the app did: the notetaker's chat aside and
 * the tree's node panel are permanent grid columns, and `Dialog` is centred.
 *
 * Everything modal about it — portal, scroll-lock, focus trap, Escape, focus
 * restore — is `Dialog`'s own `useOverlayBehaviour`, so the two can't drift.
 * All that differs is the geometry and the entrance: the panel slides in from
 * the right, and doesn't when the viewer asked for reduced motion (the global
 * `prefers-reduced-motion` rule zeroes the transition).
 */
export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  /** Panel width in px. Capped at the viewport by the stylesheet. */
  width?: number;
  side?: "right";
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  zIndex?: number;
  testid?: string;
}

export function Sheet({
  open,
  onClose,
  title,
  children,
  width = 480,
  side = "right",
  initialFocusRef,
  zIndex = 100,
  testid,
}: SheetProps) {
  const titleId = `sheet-title-${React.useId()}`;
  const { mounted, visible, panelRef, onKeyDown } = useOverlayBehaviour({
    open,
    onClose,
    initialFocusRef,
  });

  if (!mounted || !open) return null;

  return createPortal(
    <div
      className="sheet-backdrop"
      data-visible={visible || undefined}
      style={{ zIndex }}
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`sheet sheet--${side}`}
        data-visible={visible || undefined}
        data-testid={testid}
        style={{ "--sheet-width": `${width}px` } as React.CSSProperties}
      >
        <header className="sheet__header">
          <h2 id={titleId} className="sheet__title h-sans">
            {title}
          </h2>
          <button
            type="button"
            className="sheet__close"
            aria-label="Close"
            data-testid={testid ? `${testid}-close` : undefined}
            onClick={onClose}
          >
            <Icon name="x" size={16} />
          </button>
        </header>
        <div className="sheet__body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
