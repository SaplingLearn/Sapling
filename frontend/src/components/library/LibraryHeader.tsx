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
import { Glyph, FolderIcon, MENU_IN, MENU_OUT, MenuDivider, MenuScrim, CONTROL_H } from "./primitives";
import { TYPE_ORDER, TYPES, SORTS, type SortKey } from "./libraryModel";
import { cn } from "@/lib/cn";

export type HeaderMenu = "upload" | "sort" | "type" | null;

export interface LibraryHeaderProps {
  query: string;
  onQuery: (q: string) => void;
  searchRef: React.RefObject<HTMLInputElement | null>;
  fileRef: React.RefObject<HTMLInputElement | null>;
  onFiles: (files: File[]) => void;
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
      className="btn btn--sm py-0 px-4 text-md mr-2 whitespace-nowrap shrink-0 no-underline"
      style={{ height: CONTROL_H }}
    >
      <span aria-hidden="true" className="grid" style={{ color: TOOL.guide.fg }}>
        <ToolGlyph name={TOOL.guide.icon} size={14} />
      </span>
      {TOOL.guide.title}
    </Link>
  );
}

export function LibraryHeader(props: LibraryHeaderProps) {
  const {
    query, onQuery, searchRef, fileRef, onFiles, onNewFolder,
    sort, onSort, type, onType, typeCounts, scopedCount, menu, onMenu, menuClosing, canUpload,
  } = props;
  const [focused, setFocused] = React.useState(false);
  const menuAnim = menuClosing ? MENU_OUT : MENU_IN;

  const sortLabel = SORTS.find(([k]) => k === sort)?.[1] ?? "Recently Added";
  const typeLabel = type === "all" ? "All Types" : TYPES[type].label;

  return (
    <header className="relative z-20 [animation:sapFadeIn_260ms_cubic-bezier(0.2,_0.7,_0.2,_1)_900ms_both] [grid-column:1] [grid-row:1] flex items-center gap-4 mb-6">
      <div className="flex flex-col gap-3.5 shrink-0">
        <h1 className="m-0 font-serif text-[34px] font-semibold tracking-[-0.02em] leading-[1.15] shrink-0">Library</h1>

      </div>

      <label className={cn("flex-1 min-w-0 max-w-210 ml-6 flex items-center gap-2.5 box-border pt-0 pr-2 pb-0 pl-4 border border-[rgba(42,39,31,0.16)] rounded-[12px] bg-bg-panel cursor-text", focused ? "[box-shadow:0_0_0_3px_rgba(89,117,54,0.22)]" : "shadow-none")} style={{ height: CONTROL_H }}>
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
          className="flex-1 min-w-0 h-full border-0 bg-transparent [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-lg text-ink-800 outline-none"
        />

        <div className="flex items-center gap-0.5 shrink-0">
          <div className="relative">
            <button
              type="button"
              className={cn("sapHoverWarmest", "inline-flex items-center gap-2 h-8.5 py-0 px-2.5 border-0 rounded-[8px] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-text-muted whitespace-nowrap cursor-pointer", menu === "sort" ? "[background:#EDE9E0]" : "[background:transparent]")}
              onClick={() => onMenu(menu === "sort" ? null : "sort")}
              aria-haspopup="menu"
              aria-expanded={menu === "sort"}
            >
              Sort
              <span className="font-semibold text-ink-800">{sortLabel}</span>
              <Glyph name="chevronDown" size={11} fill="#6F6857" />
            </button>
            {menu === "sort" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" aria-label="Sort by" className="absolute right-0 top-11.5 z-31 w-55 [transform-origin:top_right] bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px" style={{ animation: menuAnim }}>
                  {SORTS.map(([k, label]) => (
                    <button
                      key={k}
                      type="button"
                      role="menuitemradio"
                      aria-checked={sort === k}
                      className={cn("sapHoverMenu", "flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer", sort === k ? "[background:#F2F6EE]" : "[background:transparent]")}
                      onClick={() => { onSort(k); onMenu(null); }}
                    >
                      <span className="flex-1">{label}</span>
                      <Glyph name="check" size={12} fill="#445D22" style={{ opacity: sort === k ? 1 : 0 }} />
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <span className="w-px h-5 bg-[rgba(42,39,31,0.14)]" />

          <div className="relative">
            <button
              type="button"
              className={cn("sapHoverWarmest", "inline-flex items-center gap-2 h-8.5 py-0 px-2.5 border-0 rounded-[8px] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-text-muted whitespace-nowrap cursor-pointer", menu === "type" ? "[background:#EDE9E0]" : "[background:transparent]")}
              onClick={() => onMenu(menu === "type" ? null : "type")}
              aria-haspopup="menu"
              aria-expanded={menu === "type"}
            >
              Type
              <span className="inline-flex items-center gap-1.5 font-semibold text-ink-800">
                {type !== "all" && (
                  <span className="w-2 h-2 rounded-[2px]" style={{ background: TYPES[type].color }} />
                )}
                {typeLabel}
              </span>
              <Glyph name="chevronDown" size={11} fill="#6F6857" />
            </button>
            {menu === "type" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" aria-label="Document type" className="absolute right-0 top-11.5 z-31 w-60 [transform-origin:top_right] bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px" style={{ animation: menuAnim }}>
                  {(["all", ...TYPE_ORDER] as const).map(k => {
                    const on = type === k;
                    const count = k === "all" ? scopedCount : (typeCounts[k] || 0);
                    return (
                      <button
                        key={k}
                        type="button"
                        role="menuitemradio"
                        aria-checked={on}
                        className={cn("sapHoverMenu", "flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer", on ? "[background:#F2F6EE]" : "[background:transparent]")}
                        onClick={() => { onType(k); onMenu(null); }}
                      >
                        <span className={cn("w-[9px] h-[9px] rounded-[2px] box-border shrink-0", k === "all" ? "border-[1.5px] border-ink-400" : "border-0")} style={{ background: k === "all" ? "transparent" : TYPES[k].color }} />
                        <span className="flex-1">{k === "all" ? "All Types" : TYPES[k].label}</span>
                        <span className="font-normal text-md text-text-muted">{count}</span>
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
            className="w-8 h-8 grid place-items-center border-0 rounded-[8px] bg-ink-50 text-ink-600 cursor-pointer"
          >
            <Glyph name="cross" size={12} />
          </button>
        ) : (
          <span title="Press / to search" className="min-w-6 h-6 grid place-items-center mr-1 border border-[rgba(42,39,31,0.18)] rounded-sm font-sans text-sm text-text-muted">/</span>
        )}
      </label>
        <div className="flex items-center gap-2.5 shrink-0 ml-auto">
          <GuidesButton />
          <div className="relative shrink-0 flex">
            <button
              data-testid="library-upload"
              className={cn("sapHoverForest", "inline-flex items-center gap-2 pt-0 pr-3.5 pb-0 pl-4 border-0 [background:#445D22] text-accent-fg rounded-sm [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-bold", canUpload ? "cursor-pointer" : "cursor-not-allowed", canUpload ? "opacity-100" : "opacity-55")}
              onClick={() => onMenu(menu === "upload" ? null : "upload")}
              aria-haspopup="menu"
              aria-expanded={menu === "upload"}
              disabled={!canUpload}
              title={canUpload ? "Upload documents" : "Enroll in a course first"}
              style={{ height: CONTROL_H }}
            >
              <Glyph name="upload" size={14} />
              Upload
              <span className="w-px h-4.5 mt-0 mr-0.5 mb-0 ml-1.5 bg-[rgba(255,255,255,0.3)]" />
              <Glyph name="chevronDown" size={11} />
            </button>

            <input
              ref={fileRef}
              data-testid="library-upload-input"
              type="file"
              multiple
              accept=".pdf,.pptx,.docx"
              onChange={e => {
                const files = [...(e.target.files || [])];
                if (files.length) onFiles(files);
              }}
              className="hidden"
            />

            {menu === "upload" && (
              <>
                <MenuScrim onClick={() => onMenu(null)} />
                <div role="menu" className="absolute right-0 z-31 w-59 [transform-origin:top_right] bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px" style={{ top: CONTROL_H + 6, animation: menuAnim }}>
                  <button
                    role="menuitem"
                    className="sapHoverMenu flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer"
                    onClick={() => {
                      onMenu(null);
                      const el = fileRef.current;
                      if (el) { el.value = ""; el.click(); }
                    }}
                  >
                    <Glyph name="upload" size={16} fill="#445D22" />
                    Upload Documents
                  </button>
                  <MenuDivider />
                  <button role="menuitem" className="sapHoverMenu flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [background:transparent] text-ink-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-left cursor-pointer" onClick={onNewFolder}>
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
