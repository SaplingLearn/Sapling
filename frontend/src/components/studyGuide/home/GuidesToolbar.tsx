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
  onNew: () => void;
}

/** Search and sort side by side on the left, "New study guide" on the right. */
export function GuidesToolbar({ query, onQuery, sort, onSort, onNew }: GuidesToolbarProps) {
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
      <Button variant="primary" className={s.newGuide} data-testid="guides-new" onClick={onNew}>
        <Icon name="plus" size={14} /> New study guide
      </Button>
    </div>
  );
}
