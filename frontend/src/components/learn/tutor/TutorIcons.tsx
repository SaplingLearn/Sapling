import React from "react";

/** The two layout glyphs the shared Icon set lacks: hide/show a sidebar, and
 *  hide/show the session panel. Decorative: the button names the action. */
export function SidebarGlyph({ side = "left", size = 16 }: { side?: "left" | "right"; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true" focusable="false">
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      {side === "left" ? <path d="M9 4v16" /> : <path d="M15 4v16" />}
    </svg>
  );
}

export function ChevRight({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true" focusable="false">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}
