"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui";

import type { SortKey } from "./guidesModel";
import s from "./home.module.css";
import { SortMenu } from "./SortMenu";

export interface GuidesToolbarProps {
  query: string;
  onQuery: (query: string) => void;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  /** Only the guides saved to the Library are shown. */
  savedOnly: boolean;
  onSavedOnly: (savedOnly: boolean) => void;
  onNew: () => void;
}

/** Search, sort and Saved side by side on the left, "New study guide" on the right. */
export function GuidesToolbar({ query, onQuery, sort, onSort, savedOnly, onSavedOnly, onNew }: GuidesToolbarProps) {
  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape" && query) {
      e.preventDefault();
      onQuery("");
    }
  };
  return (
    <div className={s.toolbar}>
      <label className={s.search}>
        <Icon name="search" size={14} />
        <input
          type="search"
          className={s.searchInput}
          data-testid="guides-search"
          placeholder="Search your guides"
          aria-label="Search your study guides"
          value={query}
          onChange={e => onQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
      </label>
      <SortMenu value={sort} onChange={onSort} />
      <button
        type="button"
        className={`btn ${s.savedOnly}`}
        data-testid="guides-saved-only"
        aria-pressed={savedOnly}
        title="Show only the guides saved to your Library"
        onClick={() => onSavedOnly(!savedOnly)}
      >
        <Icon name="library" size={14} />
        Saved
      </button>
      <Button variant="primary" className={s.newGuide} data-testid="guides-new" onClick={onNew}>
        <Icon name="plus" size={14} /> New study guide
      </Button>
    </div>
  );
}
