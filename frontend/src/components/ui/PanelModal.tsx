"use client";
import React from "react";
import { createPortal } from "react-dom";
import { useOverlayBehaviour } from "@/components/Dialog";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/cn";

/**
 * PanelModal — a read-mostly modal with a sticky header: a micro label on the
 * left and a "Close" button on the right, over a scrolling body.
 *
 * Calendar's Google events list and Settings' profile preview each drew this
 * same shape by hand, with their own Escape listener and scroll lock. The
 * behaviour is Dialog's (`useOverlayBehaviour`): scroll lock, focus in and
 * back out, Escape and the Tab trap.
 */
export interface PanelModalProps {
  label: string;
  onClose: () => void;
  children: React.ReactNode;
  /** Tailwind max-width class for the panel, e.g. "max-w-160". */
  maxWidth?: string;
  /** Tailwind max-height class for the panel. */
  maxHeight?: string;
  zIndex?: number;
}

export function PanelModal({
  label,
  onClose,
  children,
  maxWidth = "max-w-160",
  maxHeight = "max-h-[82vh]",
  zIndex = 120,
}: PanelModalProps) {
  const titleId = React.useId();
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open: true, onClose });
  if (!mounted) return null;

  return createPortal(
    <div
      onClick={onClose}
      onKeyDown={onKeyDown}
      className="fixed inset-0 bg-[rgba(25,_37,_11,0.45)] flex items-center justify-center p-6"
      style={{ zIndex }}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        className={cn("bg-bg rounded-lg border border-border w-full overflow-auto outline-none", maxWidth, maxHeight)}
      >
        <div className="flex justify-between items-center py-3.5 px-5 border-b border-b-border sticky top-0 bg-bg z-1">
          <div id={titleId} className="label-micro">{label}</div>
          <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" size={12} /> Close
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
