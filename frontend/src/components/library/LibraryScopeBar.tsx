"use client";
/**
 * The filter row under the header: which scope is open (the course switcher,
 * whose last option is the Trash), the folder's own Rename / Delete, the
 * notices that belong to a scope, and the List / Panel toggle.
 *
 * The "Scan <COURSE>" button is the old Library's course-wide concept scan,
 * kept and moved here — it is the one control that only makes sense while a
 * single course is open, which is exactly this row's subject.
 */
import React from "react";

import { Icon } from "../Icon";
import { Glyph, MenuDivider, MenuScrim, TrashIcon } from "./primitives";
import { ViewSwitcher, type ViewSwitcherOption } from "./ViewSwitcher";
import { cn } from "@/lib/cn";

export interface ScopeOption {
  /** "All Documents", a course code, or "No Course". */
  id: string;
  /** "Every course · 14 documents" */
  sub: string;
  color: string | null;
  on: boolean;
  pick: () => void;
  /** The Trash: a can instead of a dot, set off from the scopes above it. */
  trash?: boolean;
}

export interface LibraryScopeBarProps {
  /** "All Documents" / "MATH210 · Linear Algebra" / "MATH210 / Midterm Prep" / "Trash". */
  title: string;
  /** The dot beside the title; null for All Documents, Trash, and No Course. */
  dotColor: string | null;
  showDot: boolean;

  courseMenuOpen: boolean;
  onCourseMenu: (open: boolean) => void;
  menuClosing: boolean;
  scopeOptions: ScopeOption[];

  isTrash: boolean;

  isFolder: boolean;
  folderRenaming: boolean;
  folderDraft: string;
  onFolderDraft: (v: string) => void;
  onFolderRenameStart: () => void;
  onFolderRenameCommit: () => void;
  onFolderRenameCancel: () => void;
  onFolderDelete: () => void;

  trashHasItems: boolean;
  emptyConfirm: boolean;
  onEmptyTrash: () => void;

  /** A search running inside a course or folder offers to widen itself. */
  scoped: boolean;
  scopeName: string;
  onSearchAll: () => void;

  /** The old Library's per-course concept scan, kept. */
  courseScanLabel: string | null;
  courseScanning: boolean;
  onCourseScan: () => void;

  view: "list" | "panel";
  onView: (v: "list" | "panel") => void;
}

/** The course switcher: the heading, and the list of scopes behind it. */
function ScopeSwitcher({
  title, dotColor, showDot, open, onOpen, closing, options,
}: {
  title: string;
  dotColor: string | null;
  showDot: boolean;
  open: boolean;
  onOpen: (open: boolean) => void;
  closing: boolean;
  options: ScopeOption[];
}) {
  return (
    <div className="relative shrink-0">
      <button
        data-testid="library-course-switcher"
        className="sapHoverWarmer inline-flex items-center gap-3 h-10 -ml-3 py-0 px-3 border-0 rounded-[12px] [background:transparent] font-serif text-[24px] font-semibold tracking-[-0.01em] text-ink-800 whitespace-nowrap cursor-pointer"
        onClick={() => onOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Choose course"
      >
        {showDot && (
          <span className={cn("w-3.5 h-3.5 rounded-[50%] box-border shrink-0", dotColor ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: dotColor || "transparent" }} />
        )}
        {title}
        <Glyph name="chevronDown" size={13} fill="#6F6857" />
      </button>
      {open && (
        <>
          <MenuScrim onClick={() => onOpen(false)} />
          <div role="listbox" className={cn("absolute left-0 top-12.5 z-31 w-70 [transform-origin:top_left] bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px", closing ? "[animation:sapMenuOut_130ms_cubic-bezier(0.4,_0,_1,_1)_both]" : "[animation:sapMenuIn_170ms_cubic-bezier(0.2,_0.7,_0.2,_1)_both]")}>
            {options.map(o => (
              <React.Fragment key={o.id}>
                {o.trash && <MenuDivider />}
                <button
                  role="option"
                  aria-selected={o.on}
                  className={cn("sapHoverMenu", "flex items-start gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [font:inherit] text-left cursor-pointer", o.on ? "[background:#F2F6EE]" : "[background:transparent]")}
                  onClick={o.pick}
                >
                  <span className="flex-1 min-w-0">
                    <span className="flex items-center gap-2.5 text-base leading-[21px] font-bold">
                      {o.trash ? (
                        // The can, drawn at a size its strokes survive, in the
                        // dot's 9px slot so the label and sub-line stay aligned.
                        <span className="relative w-[9px] h-[9px] shrink-0">
                          <span className="absolute -left-0.5 -top-0.5">
                            <TrashIcon size={13} />
                          </span>
                        </span>
                      ) : (
                        <span className={cn("w-[9px] h-[9px] rounded-[50%] box-border shrink-0", o.color ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: o.color || "transparent" }} />
                      )}
                      {o.id}
                    </span>
                    <span className="block pl-[19px] text-md text-text-muted">{o.sub}</span>
                  </span>
                </button>
              </React.Fragment>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** List ⇄ Panel: the two layouts, as the switcher's options. */
const VIEW_OPTIONS: ViewSwitcherOption<"list" | "panel">[] = [
  {
    key: "list",
    label: "List",
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <rect x="1" y="2" width="14" height="2.4" rx="1" />
        <rect x="1" y="6.8" width="14" height="2.4" rx="1" />
        <rect x="1" y="11.6" width="14" height="2.4" rx="1" />
      </svg>
    ),
  },
  {
    key: "panel",
    label: "Panel",
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <rect x="1" y="1" width="6" height="6" rx="1.4" />
        <rect x="9" y="1" width="6" height="6" rx="1.4" />
        <rect x="1" y="9" width="6" height="6" rx="1.4" />
        <rect x="9" y="9" width="6" height="6" rx="1.4" />
      </svg>
    ),
  },
];

/** Rename / Delete Folder, shown only while a folder is open. */
function FolderActions({ onRename, onDelete }: { onRename: () => void; onDelete: () => void }) {
  return (
    <div className="flex gap-1">
      <button
        className="sapHoverTint h-8 py-0 px-2.5 border-0 rounded-[8px] [background:transparent] text-brand-forest [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
        onClick={onRename}
      >Rename</button>
      <button
        className="sapHoverDanger h-8 py-0 px-2.5 border-0 rounded-[8px] [background:transparent] text-[#A8443F] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
        onClick={onDelete}
      >Delete Folder</button>
    </div>
  );
}

/** The 30-day notice and the two-step Empty Trash. */
function EmptyTrash({ confirm, onClick }: { confirm: boolean; onClick: () => void }) {
  return (
    <>
      <span className="text-base text-text-muted">
        Documents in Trash are deleted forever after 30 days.
      </span>
      <button
        data-testid="library-empty-trash"
        onClick={onClick}
        className={cn("h-9 py-0 px-3.5 border-0 rounded-[9px] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold whitespace-nowrap cursor-pointer", confirm ? "bg-[#A8443F]" : "bg-[#F1D9D6]", confirm ? "text-accent-fg" : "text-[#A8443F]")}
      >{confirm ? "Click Again to Empty Trash" : "Empty Trash"}</button>
    </>
  );
}

export function LibraryScopeBar(props: LibraryScopeBarProps) {
  const {
    title, dotColor, showDot, courseMenuOpen, onCourseMenu, menuClosing, scopeOptions,
    isTrash, isFolder, folderRenaming, folderDraft, onFolderDraft,
    onFolderRenameStart, onFolderRenameCommit, onFolderRenameCancel, onFolderDelete,
    trashHasItems, emptyConfirm, onEmptyTrash, scoped, scopeName, onSearchAll,
    courseScanLabel, courseScanning, onCourseScan, view, onView,
  } = props;

  return (
    <div className="relative z-10 flex items-center gap-3 pb-3.5 border-b border-b-[rgba(42,39,31,0.10)] min-h-9.5">
      {folderRenaming ? (
        <input
          autoFocus
          value={folderDraft}
          onChange={e => onFolderDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") onFolderRenameCancel();
          }}
          onBlur={onFolderRenameCommit}
          aria-label="Folder name"
          className="h-9 py-0 px-2.5 border-[1.5px] border-brand-forest-bright rounded-[8px] bg-bg-panel font-serif text-2xl font-semibold text-ink-800 outline-none"
        />
      ) : (
        <ScopeSwitcher
          title={title}
          dotColor={dotColor}
          showDot={showDot}
          open={courseMenuOpen}
          onOpen={onCourseMenu}
          closing={menuClosing}
          options={scopeOptions}
        />
      )}

      {isFolder && !folderRenaming && (
        <FolderActions onRename={onFolderRenameStart} onDelete={onFolderDelete} />
      )}

      <span className="flex-1" />

      {courseScanLabel && !isTrash && (
        <button
          data-testid="library-course-scan"
          className={cn("sapHoverTint", "inline-flex items-center gap-[7px] h-9 py-0 px-3 border border-[rgba(42,39,31,0.14)] rounded-[9px] [background:#FDFCF9] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold whitespace-nowrap", courseScanning ? "cursor-default" : "cursor-pointer", courseScanning ? "opacity-70" : "opacity-100")}
          onClick={onCourseScan}
          disabled={courseScanning}
          title={`Extend the concept graph for ${courseScanLabel}`}
        >
          <Icon name="sparkle" size={13} />
          {courseScanning ? "Scanning…" : `Scan ${courseScanLabel}`}
        </button>
      )}

      {trashHasItems && (
        <EmptyTrash confirm={emptyConfirm} onClick={onEmptyTrash} />
      )}

      {scoped && (
        <span className="text-base text-ink-600">
          Searching in {scopeName} ·{" "}
          <button
            onClick={onSearchAll}
            className="border-0 p-0 bg-transparent text-brand-forest [font-family:inherit] [font-size:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] font-bold cursor-pointer underline [text-underline-offset:3px]"
          >Search All Documents</button>
        </span>
      )}

      <ViewSwitcher
        options={VIEW_OPTIONS}
        value={view}
        onChange={onView}
        label="Layout"
        testIdPrefix="library-view"
        style={{ marginLeft: 16 }}
      />
    </div>
  );
}
