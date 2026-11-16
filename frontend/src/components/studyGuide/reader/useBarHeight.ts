"use client";
import React from "react";

/**
 * Keeps `--guide-bar` on the reader's page at the height of its top bar.
 *
 * The generation banner, the rail and the section anchors sit under that
 * sticky bar. Its height is not a constant: on a phone its actions wrap to a
 * second row. The stylesheets fall back to one row where nothing measures.
 */
export function useBarHeight(page: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    const el = page.current;
    const bar = el?.querySelector<HTMLElement>(":scope > header");
    if (!el || !bar || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => el.style.setProperty("--guide-bar", `${bar.offsetHeight}px`));
    observer.observe(bar);
    return () => observer.disconnect();
  }, [page]);
}
