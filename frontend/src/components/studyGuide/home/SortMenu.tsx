"use client";
import { Icon } from "@/components/Icon";
import { Menu, MenuContent, MenuRadioGroup, MenuRadioItem, MenuTrigger } from "@/components/ui/Menu";

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
  return (
    <div className={s.sortOwner}>
      <Menu>
        <MenuTrigger asChild>
          <button
            type="button"
            className={`btn ${s.sort}`}
            data-testid="guides-sort"
            aria-label={`Sort: ${sortLabel(value)}`}
          >
            <SortGlyph />
            {sortLabel(value)}
            <span aria-hidden="true" className={s.sortChevron}><Icon name="chevron-down" size={10} /></span>
          </button>
        </MenuTrigger>
        <MenuContent label="Sort guides">
          <MenuRadioGroup value={value} onValueChange={v => onChange(v as SortKey)}>
            {SORTS.map(sort => (
              <MenuRadioItem key={sort.key} value={sort.key} data-testid={`guides-sort-${sort.key}`} check={<Icon name="check" size={14} />}>
                {sort.label}
              </MenuRadioItem>
            ))}
          </MenuRadioGroup>
        </MenuContent>
      </Menu>
    </div>
  );
}
