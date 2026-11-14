"use client";
import { Icon } from "@/components/Icon";

import { useMenu } from "../shared/useMenu";
import { SORTS, sortLabel, type SortKey } from "./guidesModel";
import s from "./home.module.css";

/** Three lines, each shorter than the last. */
function SortGlyph() {
  return (
    <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <path d="M3 6h18M6.5 12h11M10 18h4" />
    </svg>
  );
}

/** The sort button shows only the current choice; the menu holds the rest. */
export function SortMenu({ value, onChange }: { value: SortKey; onChange: (sort: SortKey) => void }) {
  const { open, toggle, close, owner, onKeyDown, onBlur } = useMenu();

  const pick = (sort: SortKey) => {
    close();
    onChange(sort);
  };

  return (
    <div ref={owner} className={s.sortOwner} onKeyDown={onKeyDown} onBlur={onBlur}>
      <button
        type="button"
        className={`btn ${s.sort}`}
        data-testid="guides-sort"
        aria-label={`Sort: ${sortLabel(value)}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        <SortGlyph />
        {sortLabel(value)}
        <span aria-hidden="true" className={s.sortChevron}><Icon name="chevron-down" size={10} /></span>
      </button>
      {open && (
        <div role="menu" aria-label="Sort guides" className={`${s.menu} fade-in`}>
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
              {sort.key === value && <Icon name="check" size={14} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
