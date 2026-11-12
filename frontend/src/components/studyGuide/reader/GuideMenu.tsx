"use client";
import React from "react";
import Link from "next/link";

import { Icon } from "@/components/Icon";

import s from "./reader.module.css";

function DotsGlyph() {
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="5" cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="19" cy="12" r="2" />
    </svg>
  );
}

function RegenerateGlyph() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
    </svg>
  );
}

/** Close on Escape, and on a press anywhere outside `ref`. */
function useDismiss(ref: React.RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  React.useEffect(() => {
    if (!open) return;
    const onPress = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onPress);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPress);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close]);
}

/** The three-dot menu beside the title. */
export function GuideMenu({
  saved,
  busy,
  onSave,
  onRegenerate,
}: {
  saved: boolean;
  /** The guide is being written: it cannot be regenerated on top of that. */
  busy: boolean;
  onSave: () => void;
  onRegenerate: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const wrap = React.useRef<HTMLDivElement>(null);
  const close = React.useCallback(() => setOpen(false), []);
  useDismiss(wrap, open, close);

  const exportPdf = () => {
    close();
    window.print();
  };
  const regenerate = () => {
    close();
    onRegenerate();
  };

  return (
    <div className={s.menuWrap} ref={wrap}>
      <button
        type="button"
        className={s.menuButton}
        data-testid="guide-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions for this guide"
        onClick={() => setOpen(!open)}
      >
        <DotsGlyph />
      </button>
      {open && (
        <div role="menu" aria-label="Guide actions" className={`${s.menu} fade-in`}>
          {saved ? (
            <Link role="menuitem" href="/library" className={s.menuItem} data-testid="guide-menu-saved">
              <Icon name="check" size={14} />
              <span className={s.menuSaved}>
                <strong>Saved to Library</strong>
                <span>Open it there</span>
              </span>
            </Link>
          ) : (
            <button type="button" role="menuitem" className={s.menuItem} data-testid="guide-menu-save" onClick={onSave}>
              <Icon name="library" size={16} />
              Save to Library
            </button>
          )}
          <button type="button" role="menuitem" className={s.menuItem} data-testid="guide-menu-export" onClick={exportPdf}>
            <Icon name="download" size={16} />
            Export PDF
          </button>
          <span className={s.menuRule} aria-hidden="true" />
          <button
            type="button"
            role="menuitem"
            className={s.menuItem}
            data-testid="guide-menu-regenerate"
            onClick={regenerate}
            disabled={busy}
          >
            <RegenerateGlyph />
            Regenerate whole guide
          </button>
        </div>
      )}
    </div>
  );
}
