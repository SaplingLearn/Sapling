"use client";
/**
 * The Library's two keyboard shortcuts: `/` focuses the search, and the arrow
 * keys walk the selection down and up the list.
 *
 * The visible order is passed in on every render and kept in a ref, so the
 * handler always steers the list as it is now without re-binding each time it
 * is filtered or sorted.
 */
import React from "react";

export interface LibraryKeysInput {
  /** The ids currently listed, in display order. */
  ids: string[];
  searchRef: React.RefObject<HTMLInputElement | null>;
  setSelected: React.Dispatch<React.SetStateAction<string | null>>;
}

export function useLibraryKeys({ ids, searchRef, setSelected }: LibraryKeysInput): void {
  const idsRef = React.useRef<string[]>(ids);
  React.useEffect(() => { idsRef.current = ids; }, [ids]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const tag = (target?.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "select" || tag === "textarea"
        || target?.isContentEditable === true;

      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      // The search box is the one field the arrows still steer the list from.
      if (typing && target !== searchRef.current) return;

      const list = idsRef.current;
      if (!list.length) return;
      e.preventDefault();
      setSelected(prev => {
        const i = list.indexOf(prev ?? "");
        const next = e.key === "ArrowDown"
          ? Math.min(list.length - 1, i + 1)
          : Math.max(0, i - 1);
        return list[next < 0 ? 0 : next];
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [searchRef, setSelected]);
}
