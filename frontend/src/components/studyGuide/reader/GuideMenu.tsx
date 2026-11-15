"use client";
import React from "react";
import Link from "next/link";

import { Icon } from "@/components/Icon";
import { useMenu } from "@/components/studyGuide/shared/useMenu";

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

/** The three-dot menu beside the title. */
export function GuideMenu({
  saved,
  busy,
  onSave,
  onRegenerate,
}: {
  saved: boolean;
  /** The guide or one of its blocks is being written: it cannot be regenerated on top of that. */
  busy: boolean;
  onSave: () => void;
  onRegenerate: () => void;
}) {
  const { open, toggle, close, owner, onKeyDown, onBlur } = useMenu();
  const savedItem = React.useRef<HTMLAnchorElement>(null);
  // Save swaps the item that has the focus for this one. Follow it, or the
  // focus falls to the page and the keyboard loses the menu.
  React.useEffect(() => {
    if (open && saved) savedItem.current?.focus();
  }, [open, saved]);

  const exportPdf = () => {
    close();
    window.print();
  };
  const regenerate = () => {
    close();
    onRegenerate();
  };

  return (
    <div className={s.menuWrap} ref={owner} onKeyDown={onKeyDown} onBlur={onBlur}>
      <button
        type="button"
        className={s.menuButton}
        data-testid="guide-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More actions for this guide"
        onClick={toggle}
      >
        <DotsGlyph />
      </button>
      {open && (
        <div role="menu" aria-label="Guide actions" className={`${s.menu} fade-in`}>
          {saved ? (
            <Link ref={savedItem} role="menuitem" href="/library" className={s.menuItem} data-testid="guide-menu-saved">
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
