"use client";
/**
 * The Library's top row: the title, the Upload split button with its New
 * menu, and the search field that carries the Sort and Type dropdowns.
 *
 * Every value is the design handoff's literal — see `Sapling Library v2.dc.html`.
 */
import React from "react";
import Link from "next/link";

import type { Document as Doc } from "@/lib/types";
import { Glyph as ToolGlyph, TOOL } from "../study/hubUi";
import { studyGuideHref } from "@/lib/toolHrefs";
import {
  FONT_MONO, FONT_SERIF, Glyph, FolderIcon, MENU_IN, MENU_ITEM, MENU_OUT,
  MENU_SURFACE, MenuDivider, MenuScrim,
  CONTROL_H,
} from "./primitives";
import { TYPE_ORDER, TYPES, SORTS, type SortKey } from "./libraryModel";

export type HeaderMenu = "upload" | "sort" | "type" | null;

export interface LibraryHeaderProps {
  query: string;
  onQuery: (q: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  fileRef: React.RefObject<HTMLInputElement | null>;
  onFiles: (files: File[]) => void;
  onNewDocument: () => void;
  onNewFolder: () => void;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  type: Doc["category"] | "all";
  onType: (t: Doc["category"] | "all") => void;
  /** How many documents of each type the current scope holds, before the type filter. */
  typeCounts: Record<string, number>;
  scopedCount: number;
  menu: HeaderMenu;
  /** Null closes the open menu through the exit animation. */
  onMenu: (m: HeaderMenu) => void;
  menuClosing: boolean;
  /** Disabled until the student is enrolled in something to upload into. */
  canUpload: boolean;
}

/**
 * The way out to the Study Guides hub.
 *
 * The guides used to be listed inline above the documents; the hub owns that
 * list, and the design handoff has no guides section at all (it knows "Study
 * Guide" only as a document category).
 *
 * Sized to match Upload beside it — same 48px height, 12px radius and 15/700
 * type — so the two read as one pair of page actions rather than a primary
 * button with a chip stuck to it. It keeps the Study hub's `TOOL.guide` tint
 * on the glyph, and the secondary surface, so Upload is still clearly the
 * primary of the two.
 */
function GuidesButton() {
  return (
    <Link
      href={studyGuideHref()}
      data-testid="library-guides"
      className="btn btn--sm"
      style={{
        height: CONTROL_H, padding: "0 16px", fontSize: "var(--fs-md)",
        // Owner's call 2026-11-25: sit a little further left, so the pair is
        // not read as one split control.
        marginRight: 8,
        whiteSpace: "nowrap", flexShrink: 0, textDecoration: "none",
      }}
    >
      <span aria-hidden="true" style={{ display: "grid", color: TOOL.guide.fg }}>
        <ToolGlyph name={TOOL.guide.icon} size={14} />
      </span>
      {TOOL.guide.title}
    </Link>
  );
}

export function LibraryHeader(props: LibraryHeaderProps) {
  const {
    query, onQuery, searchRef, fileRef, onFiles, onNewDocument, onNewFolder,
    sort, onSort, type, onType, typeCounts, scopedCount, menu, onMenu, menuClosing, canUpload,
  } = props;
  const [focused, setFocused] = React.useState(false);
  const menuAnim = menuClosing ? MENU_OUT : MENU_IN;

  // Escape closes whichever header menu is open. The design handoff binds
  // Escape only inside text inputs, so a menu opened by keyboard could be
  // dismissed only by clicking its scrim — which is a mouse-only exit from a
  // keyboard-reachable control. One listener covers all three menus because
  // they share `menu`/`onMenu`, and it closes through the same exit animation
  // a scrim click does.
  React.useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onMenu(null); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menu, onMenu]);

  const sortLabel = SORTS.find(([k]) => k === sort)?.[1] ?? "Recently Added";
  const typeLabel = type === "all" ? "All Types" : TYPES[type].label;

  return (
    <header style={{
      position: "relative",
      zIndex: 20,
      animation: "sapFadeIn 260ms cubic-bezier(0.2, 0.7, 0.2, 1) 900ms both",
      gridColumn: 1,
      gridRow: 1,
      display: "flex",
      alignItems: "center",
      gap: 16,
      marginBottom: 24,
    }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, flexShrink: 0 }}>
        <h1 style={{
          margin: 0,
          fontFamily: FONT_SERIF,
          fontSize: 34,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          lineHeight: 1.15,
          flexShrink: 0,
        }}>Library</h1>

      </div>

      <label style={{
        flex: 1,
        minWidth: 0,
        maxWidth: 840,
        marginLeft: 24,
        display: "flex",
        alignItems: "center",
        gap: 10,
        height: CONTROL_H,
        boxSizing: "border-box",
        padding: "0 8px 0 16px",
        border: "1px solid rgba(42,39,31,0.16)",
        borderRadius: 12,
        background: "#FDFCF9",
        boxShadow: focused ? "0 0 0 3px rgba(89,117,54,0.22)" : "none",
        cursor: "text",
      }}>
        <Glyph name="search" size={18} fill="#6F6857" />
        <input
          data-testid="library-search"
          ref={searchRef}
          value={query}
          onChange={e => onQuery(e.target.value)}
          onKeyDown={e => { if (e.key === "Escape") onQuery(""); }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Search titles, summaries, and concepts"
          aria-label="Search documents"
          style={{
            flex: 1, minWidth: 0, height: "100%", border: 0, background: "transparent",
            font: "inherit", fontSize: 16, color: "#1A1814", outline: "none",
          }}
        />

        <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
          <div style={{ position: "relative" }}>
            <button
              type="button"
              className="sapHoverWarmest"
              onClick={() => onMenu(menu === "sort" ? null : "sort")}
              aria-haspopup="menu"
              aria-expanded={menu === "sort"}
              style={{
                display: "inline-flex", alignItems: "center", gap: 8, height: 34,
                padding: "0 10px", border: 0, borderRadius: 8,
                background: menu === "sort" ? "#EDE9E0" : "transparent",
                font: "inherit", fontSize: 14, color: "#6F6857",
                whiteSpace: "nowrap", cursor: "pointer",
              }}
            >
              Sort
              <span style={{ fontWeight: 600, color: "#1A1814" }}>{sortLabel}</span>
              <Glyph name="chevronDown" size={11} fill="#6F6857" />
            </button>
            {menu === "sort" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" aria-label="Sort by" style={{
                  position: "absolute", right: 0, top: 46, zIndex: 31, width: 220,
                  transformOrigin: "top right", animation: menuAnim, ...MENU_SURFACE,
                }}>
                  {SORTS.map(([k, label]) => (
                    <button
                      key={k}
                      type="button"
                      role="menuitemradio"
                      aria-checked={sort === k}
                      className="sapHoverMenu"
                      onClick={() => { onSort(k); onMenu(null); }}
                      style={{ ...MENU_ITEM, background: sort === k ? "#F2F6EE" : "transparent" }}
                    >
                      <span style={{ flex: 1 }}>{label}</span>
                      <Glyph name="check" size={12} fill="#445D22" style={{ opacity: sort === k ? 1 : 0 }} />
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <span style={{ width: 1, height: 20, background: "rgba(42,39,31,0.14)" }} />

          <div style={{ position: "relative" }}>
            <button
              type="button"
              className="sapHoverWarmest"
              onClick={() => onMenu(menu === "type" ? null : "type")}
              aria-haspopup="menu"
              aria-expanded={menu === "type"}
              style={{
                display: "inline-flex", alignItems: "center", gap: 8, height: 34,
                padding: "0 10px", border: 0, borderRadius: 8,
                background: menu === "type" ? "#EDE9E0" : "transparent",
                font: "inherit", fontSize: 14, color: "#6F6857",
                whiteSpace: "nowrap", cursor: "pointer",
              }}
            >
              Type
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                fontWeight: 600, color: "#1A1814",
              }}>
                {type !== "all" && (
                  <span style={{
                    width: 8, height: 8, borderRadius: 2, background: TYPES[type].color,
                  }} />
                )}
                {typeLabel}
              </span>
              <Glyph name="chevronDown" size={11} fill="#6F6857" />
            </button>
            {menu === "type" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" aria-label="Document type" style={{
                  position: "absolute", right: 0, top: 46, zIndex: 31, width: 240,
                  transformOrigin: "top right", animation: menuAnim, ...MENU_SURFACE,
                }}>
                  {(["all", ...TYPE_ORDER] as const).map(k => {
                    const on = type === k;
                    const count = k === "all" ? scopedCount : (typeCounts[k] || 0);
                    return (
                      <button
                        key={k}
                        type="button"
                        role="menuitemradio"
                        aria-checked={on}
                        className="sapHoverMenu"
                        onClick={() => { onType(k); onMenu(null); }}
                        style={{ ...MENU_ITEM, background: on ? "#F2F6EE" : "transparent" }}
                      >
                        <span style={{
                          width: 9, height: 9, borderRadius: 2,
                          background: k === "all" ? "transparent" : TYPES[k].color,
                          border: k === "all" ? "1.5px solid #8A8372" : "0",
                          boxSizing: "border-box", flexShrink: 0,
                        }} />
                        <span style={{ flex: 1 }}>{k === "all" ? "All Types" : TYPES[k].label}</span>
                        <span style={{ fontWeight: 400, fontSize: 13, color: "#6F6857" }}>{count}</span>
                        <Glyph name="check" size={12} fill="#445D22" style={{ opacity: on ? 1 : 0 }} />
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        {query ? (
          <button
            onClick={() => onQuery("")}
            aria-label="Clear search"
            style={{
              width: 32, height: 32, display: "grid", placeItems: "center", border: 0,
              borderRadius: 8, background: "#F4F1EA", color: "#3F3B31", cursor: "pointer",
            }}
          >
            <Glyph name="cross" size={12} />
          </button>
        ) : (
          <span title="Press / to search" style={{
            minWidth: 24, height: 24, display: "grid", placeItems: "center", marginRight: 4,
            border: "1px solid rgba(42,39,31,0.18)", borderRadius: 6,
            fontFamily: FONT_MONO, fontSize: 12, color: "#6F6857",
          }}>/</span>
        )}
      </label>
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          flexShrink: 0, marginLeft: "auto",
        }}>
          <GuidesButton />
          <div style={{ position: "relative", flexShrink: 0, display: "flex" }}>
            <button
              data-testid="library-upload"
              className="sapHoverForest"
              onClick={() => onMenu(menu === "upload" ? null : "upload")}
              aria-haspopup="menu"
              aria-expanded={menu === "upload"}
              disabled={!canUpload}
              title={canUpload ? "Upload documents" : "Enroll in a course first"}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                height: CONTROL_H,
                padding: "0 14px 0 16px",
                border: 0,
                background: "#445D22",
                color: "#FFFFFF",
                // Owner's call 2026-11-25: the same edge as the Study Guide
                // button beside it, rather than the handoff's 12px, so the
                // pair matches. That button is `btn btn--sm`, whose
                // `var(--r-sm)` resolves to 6px — written as the number so the
                // rendered value stays one the design names, which is what
                // `designParity` checks every radius against.
                borderRadius: 6,
                font: "inherit",
                // Owner's call 2026-11-25: the Study Guide button beside it is
                // `btn btn--sm`, whose type is `--fs-md`. Upload read a size
                // and an icon larger than its neighbour; both come down to
                // match. The 700 weight stays — it is still the primary.
                fontSize: "var(--fs-md)",
                fontWeight: 700,
                cursor: canUpload ? "pointer" : "not-allowed",
                opacity: canUpload ? 1 : 0.55,
              }}
            >
              <Glyph name="upload" size={14} />
              Upload
              <span style={{
                width: 1, height: 18, margin: "0 2px 0 6px", background: "rgba(255,255,255,0.3)",
              }} />
              <Glyph name="chevronDown" size={11} />
            </button>

            <input
              ref={fileRef}
              type="file"
              multiple
              accept=".pdf,.pptx,.docx"
              onChange={e => {
                const files = [...(e.target.files || [])];
                if (files.length) onFiles(files);
              }}
              style={{ display: "none" }}
            />

            {menu === "upload" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" style={{
                  // `right: 0` is the handoff's own anchor, and the rebuild
                  // had it as `left: 0` — a porting slip. Upload is the last
                  // thing in the header, so a 236px menu hung off its LEFT ran
                  // past the window and clipped. `top` follows the control
                  // height: the prototype's 54 is its 48px button plus 6.
                  position: "absolute", right: 0, top: CONTROL_H + 6,
                  zIndex: 31, width: 236,
                  transformOrigin: "top right", animation: menuAnim, ...MENU_SURFACE,
                }}>
                  <button
                    role="menuitem"
                    className="sapHoverMenu"
                    onClick={() => {
                      onMenu(null);
                      const el = fileRef.current;
                      if (el) { el.value = ""; el.click(); }
                    }}
                    style={MENU_ITEM}
                  >
                    <Glyph name="upload" size={16} fill="#445D22" />
                    Upload Documents
                  </button>
                  <MenuDivider />
                  <button role="menuitem" className="sapHoverMenu" onClick={onNewDocument} style={MENU_ITEM}>
                    <svg
                      width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#445D22"
                      strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true"
                    >
                      <path d="M6 3h8l4 4v14H6z" />
                      <path d="M14 3v4h4" />
                    </svg>
                    New Document
                  </button>
                  <button role="menuitem" className="sapHoverMenu" onClick={onNewFolder} style={MENU_ITEM}>
                    <FolderIcon size={16} />
                    New Folder
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
    </header>
  );
}
