"use client";
import React from "react";
import Link from "next/link";

import { Icon } from "@/components/Icon";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/Menu";
import { studyGuideHref } from "@/lib/toolHrefs";

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
  const [open, setOpen] = React.useState(false);
  const savedItem = React.useRef<HTMLAnchorElement>(null);
  // Save swaps the item that has the focus for this one. Follow it, or the
  // focus falls to the page and the keyboard loses the menu.
  React.useEffect(() => {
    if (open && saved) savedItem.current?.focus();
  }, [open, saved]);

  return (
    <div className={s.menuWrap}>
      <Menu open={open} onOpenChange={setOpen}>
        <MenuTrigger asChild>
          <button
            type="button"
            className={s.menuButton}
            data-testid="guide-menu"
            aria-label="More actions for this guide"
          >
            <DotsGlyph />
          </button>
        </MenuTrigger>
        <MenuContent label="Guide actions" align="end" width="w-62.5">
          {saved ? (
            // The Study Guides home with Saved on, not /library: since the
            // Library rebuild (#717) the home is the one place that lists
            // saved guides.
            <MenuItem asChild>
              <Link ref={savedItem} href={studyGuideHref({ saved: true })} data-testid="guide-menu-saved">
                <Icon name="check" size={14} />
                <span className={s.menuSaved}>
                  <strong>Saved to Library</strong>
                  <span>Open it there</span>
                </span>
              </Link>
            </MenuItem>
          ) : (
            // Saving keeps the menu open: the item turns into "Saved to Library".
            <MenuItem data-testid="guide-menu-save" onSelect={(e) => { e.preventDefault(); onSave(); }}>
              <Icon name="library" size={16} />
              Save to Library
            </MenuItem>
          )}
          <MenuItem data-testid="guide-menu-export" onSelect={() => window.print()}>
            <Icon name="download" size={16} />
            Export PDF
          </MenuItem>
          <MenuSeparator />
          <MenuItem data-testid="guide-menu-regenerate" disabled={busy} onSelect={onRegenerate}>
            <RegenerateGlyph />
            Regenerate whole guide
          </MenuItem>
        </MenuContent>
      </Menu>
    </div>
  );
}
