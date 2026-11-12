"use client";
import React from "react";

import { Icon } from "@/components/Icon";

import { SORTS, sortLabel, type SortKey } from "./guidesModel";
import s from "./home.module.css";

/** Closes the menu on Esc (focus back on its button) or a press outside it. */
function useDismiss(open: boolean, owner: React.RefObject<HTMLDivElement | null>, close: () => void) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      close();
      owner.current?.querySelector<HTMLElement>("button")?.focus();
    };
    const onDown = (e: Event) => {
      if (owner.current && e.target instanceof Node && owner.current.contains(e.target)) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open, owner, close]);
}

/** The sort button shows only the current choice; the menu holds the rest. */
export function SortMenu({ value, onChange }: { value: SortKey; onChange: (sort: SortKey) => void }) {
  const [open, setOpen] = React.useState(false);
  const owner = React.useRef<HTMLDivElement | null>(null);
  const close = React.useCallback(() => setOpen(false), []);
  useDismiss(open, owner, close);

  const pick = (sort: SortKey) => {
    close();
    onChange(sort);
  };

  return (
    <div ref={owner} className={s.sortOwner}>
      <button
        type="button"
        className={`btn ${s.sort}`}
        data-testid="guides-sort"
        aria-label={`Sort: ${sortLabel(value)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
      >
        {sortLabel(value)}
        <span aria-hidden="true" className={s.sortChevron}><Icon name="chevron-down" size={10} /></span>
      </button>
      {open && (
        <div role="menu" aria-label="Sort guides" className={s.menu}>
          {SORTS.map(sort => (
            <button
              key={sort.key}
              type="button"
              role="menuitemradio"
              aria-checked={sort.key === value}
              className={s.menuItem}
              data-testid={`guides-sort-${sort.key}`}
              onClick={() => pick(sort.key)}
            >
              {sort.label}
              {sort.key === value && <Icon name="check" size={12} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
