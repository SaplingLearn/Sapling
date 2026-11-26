"use client";
/**
 * The small pieces the Library markup repeats: the brand glyphs, the single
 * -path strokes the design inlines (folder, trash, chevrons, the row's ⋯), and
 * the two controls that appear a dozen times each (a course dot, a checkbox).
 *
 * Every `viewBox`, `d`, size and colour is the design handoff's, verbatim.
 */
import React from "react";
import { GLYPHS, type GlyphName } from "./glyphs";
import { cn } from "@/lib/cn";

export const FONT_SERIF = "var(--font-serif)";
export const FONT_SANS = "var(--font-sans)";
/**
 * The handoff's IBM Plex Mono slot. Plex Mono is gone from the app (#928), so
 * this is SUSE, as `.mono` in globals.css now is. The name stays so every
 * handoff "mono" spot stays findable against the design.
 */
export const FONT_MONO = "var(--font-sans)";

/** One of the filled brand glyphs from `glyphs.ts`. */
export function Glyph({
  name, size, fill = "currentColor", style,
}: {
  name: GlyphName;
  size: number;
  fill?: string;
  style?: React.CSSProperties;
}) {
  const g = GLYPHS[name];
  return (
    <svg width={size} height={size} viewBox={g.vb} fill={fill} aria-hidden="true" style={style}>
      {g.d.map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

/** The filled folder, always #B8873F. `stroke-width` varies by size. */
export function FolderIcon({ size, strokeWidth = 2 }: { size: number; strokeWidth?: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0.5 24 24"
      fill="#B8873F" stroke="#B8873F" strokeWidth={strokeWidth} strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2.2h8.4A1.5 1.5 0 0 1 21 8.7v9.8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z" />
    </svg>
  );
}

/** The square a folder row's icon sits in, matched to a document's tile. */
export const FOLDER_TILE: React.CSSProperties = {
  width: 30,
  height: 38,
  display: "grid",
  placeItems: "center",
  flexShrink: 0,
};

/** The ">" a folder row and the Open menu item use. */
export function ChevronRight({ size }: { size: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d="M9 5l7 7-7 7" />
    </svg>
  );
}

/** The row's "⋯" affordance. */
export function DotsIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.9" />
      <circle cx="12" cy="12" r="1.9" />
      <circle cx="19" cy="12" r="1.9" />
    </svg>
  );
}

/** The trash can: the Trash's marker in the scope switcher. */
export function TrashIcon({ size }: { size: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#6F6857"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      className="block shrink-0"
    >
      <path d="M4 7h16" />
      <path d="M9 7V4.5h6V7" />
      <path d="M6 7l1 13h10l1-13" />
      <path d="M10 11v5.5M14 11v5.5" />
    </svg>
  );
}

/**
 * A course's colour dot. A document with no course gets the design's dashed
 * outline instead of a fill, so "no course" reads as a gap rather than a
 * colour of its own.
 */
export function CourseDot({
  color, size = 8, style,
}: {
  color: string | null;
  size?: number;
  style?: React.CSSProperties;
}) {
  return (
    <span className={cn("rounded-[50%] box-border shrink-0", color ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ width: size, height: size, background: color || "transparent", ...style }} />
  );
}

/** The square check used by the select-all header and every row. */
export function CheckBox({
  checked, onClick, label, size = 20, radius = 5, background,
}: {
  checked: boolean;
  onClick: (e: React.MouseEvent) => void;
  label: string;
  size?: number;
  radius?: number;
  /** The card variant sits on a thumbnail, so its unchecked fill is translucent. */
  background?: string;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      aria-pressed={checked}
      className={cn("text-accent-fg grid place-items-center p-0 cursor-pointer", checked ? "border-[1.5px] border-brand-forest" : "border-[1.5px] border-[rgba(42,39,31,0.28)]")} style={{ width: size, height: size, borderRadius: radius, background: checked ? "#445D22" : background || "#FDFCF9" }}
    >
      <Glyph name="check" size={11} style={{ opacity: checked ? 1 : 0 }} />
    </button>
  );
}

/** The shared surface every popover in the design uses. */
export const MENU_SURFACE: React.CSSProperties = {
  background: "#FDFCF9",
  border: "1px solid rgba(42,39,31,0.14)",
  borderRadius: 12,
  boxShadow: "0 14px 36px rgba(25,37,11,0.16)",
  padding: 6,
  display: "flex",
  flexDirection: "column",
  gap: 1,
};

/** The shared shape of a row inside one of those popovers. */
export const MENU_ITEM: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "9px 10px",
  border: 0,
  borderRadius: 8,
  background: "transparent",
  color: "#1A1814",
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  textAlign: "left",
  cursor: "pointer",
};

/** The hairline the menus put between groups. */
export function MenuDivider() {
  return <span className="h-px my-1 mx-1.5 bg-[rgba(42,39,31,0.10)]" />;
}

/** A menu's group heading: sentence case, no tracking (#928 retired the mono caps). */
export const MENU_HEADING: React.CSSProperties = {
  padding: "6px 10px 4px",
  fontFamily: FONT_MONO,
  fontSize: 13,
  color: "#6F6857",
};

/** A click-anywhere-else backdrop, under a popover and over everything else. */
export function MenuScrim({ onClick, zIndex = 30 }: { onClick: () => void; zIndex?: number }) {
  return <div onClick={onClick} className="fixed inset-0" style={{ zIndex }} />;
}

export const MENU_IN = "sapMenuIn 170ms cubic-bezier(0.2, 0.7, 0.2, 1) both";
export const MENU_OUT = "sapMenuOut 130ms cubic-bezier(0.4, 0, 1, 1) both";

/**
 * The header controls' shared height.
 *
 * The handoff draws the search field and Upload at 48px. Owner's call
 * 2026-11-25: too heavy for the row, so both come DOWN to the Study hub tool
 * button's own 40px — that button is unchanged — and the skeleton's matching
 * bars follow. Only the height moves; every padding, radius and type size
 * stays the handoff's. Named once so the three cannot drift apart.
 */
export const CONTROL_H = 40;
