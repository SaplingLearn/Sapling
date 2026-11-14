/**
 * What the Study hub's panels share: its type faces, the three tools' look,
 * the pop-up surface, and the small glyphs the repo's Icon set doesn't carry.
 *
 * Type and colour come from the app tokens (globals.css), the ones the
 * Dashboard is built on. Titles and figures use the display face, as its
 * `.h-serif` does; micro labels are `.label-micro`; buttons are `.btn`.
 */
import React from "react";
import { Icon } from "../Icon";
import { TC, type Status } from "./studyModel";
import type { ToolKey } from "./useToolNav";

export const DISPLAY = "var(--font-display)";
export const SANS = "var(--font-sans)";
export const MONO = "var(--font-mono)";

/** One line, cut with an ellipsis. */
export const ELLIPSIS: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

/** The surface of the hub's pop-ups (deadlines, tile menu, Quick Reviews). */
export const POPOVER: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-md)",
  boxShadow: "var(--shadow-lg)",
};

/** Each tool's name, glyph and tint, wherever the hub shows it. */
export const TOOL: Record<ToolKey, { title: string; icon: GlyphName; bg: string; fg: string }> = {
  quiz: { title: "Quiz", icon: "bulb", bg: "#EBDDEE", fg: "#7A4A78" },
  cards: { title: "Flashcards", icon: "cards", bg: "var(--sap-100)", fg: "var(--brand-forest)" },
  guide: { title: "Study Guide", icon: "file", bg: "#F1E3C4", fg: "var(--warn)" },
};
/** The order the tools are offered in. */
export const TOOL_ORDER: ToolKey[] = ["quiz", "cards", "guide"];

/** The tools on offer: hide_quiz (#620) hides Quiz everywhere it appears. */
export const shownTools = <T extends { key: ToolKey }>(items: T[], quizShown: boolean): T[] =>
  items.filter(item => item.key !== "quiz" || quizShown);

export type GlyphName = "bulb" | "cards" | "file";

export function CardsIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7 3h11a2 2 0 0 1 2 2v11h-2V5H7z" />
      <path d="M4 7h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
    </svg>
  );
}

/* Prerequisite warning glyph: Sapling's leaf-shaped error badge (exclamation
   knocked out, so the banner's cream shows through), in the warning amber the
   design's round icon used rather than the badge's source green. */
export function WarnIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
      <path
        fill="var(--warn)"
        d="M23.62,17.47c-.56-1.65-.86-3.75-1.75-5.26-.69-.94-1.05-2.34-1.77-3.2-.19-.25-.44-.49-.61-.76-1.48-2.92-4.17-5.22-6.64-7.34-.25-.21-.56-.37-.89-.37-.46.03-.93.11-1.41.4-.56.49-.8.93-1.33,1.42-.67.58-1.29,1.35-1.79,2.04-.67.75-1.44,1.34-1.97,2.18-.88,1.25-1.87,2.76-2.53,4.11-.22.71-.64,1.22-1,1.86-.71,1.31-.84,2.85-1.35,4.26-.2.67-.36,1.34-.19,2.03.33,1.38,1.7,1.93,2.93,2.26,1.08.4,2.1.83,3.25,1.11.61.15,1.28.05,1.8.1.74.33,1.72.18,2.37.7.37.24.75.49,1.22.47.7,0,1.13-.55,1.73-.78.57-.13,1.4-.16,1.95-.39,1.7.14,3.35-.54,4.94-1.14,1.58-.49,3.39-1.69,3.05-3.56l-.02-.11ZM11.78,19.32c-.78,0-1.41-.63-1.41-1.41s.63-1.41,1.41-1.41,1.41.64,1.41,1.41-.63,1.41-1.41,1.41ZM13.28,14.14c-.05.74-.66,1.31-1.4,1.31h-.2c-.74,0-1.35-.57-1.4-1.31l-.51-7.05c-.05-.82.59-1.51,1.41-1.51h1.2c.82,0,1.47.69,1.41,1.51l-.51,7.05Z"
      />
    </svg>
  );
}

export function Glyph({ name, size }: { name: GlyphName; size: number }) {
  return name === "cards" ? <CardsIcon size={size} /> : <Icon name={name} size={size} />;
}

/** A round status dot (legend, prerequisite chips, Quick Reviews). `fixed`
 *  keeps it from being squeezed in a row whose text can be cut short. */
export function StatusDot({ st, size, fixed = false }: { st: Status; size: number; fixed?: boolean }) {
  return <span style={{ width: size, height: size, borderRadius: "50%", background: TC[st], flexShrink: fixed ? 0 : undefined }} />;
}
