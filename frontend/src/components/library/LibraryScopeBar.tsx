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
import {
  FONT_SERIF, Glyph, MENU_IN, MENU_OUT, MENU_SURFACE, MenuDivider, MenuScrim, TrashIcon,
} from "./primitives";
import { ViewSwitcher, type ViewSwitcherOption } from "./ViewSwitcher";

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

  /** Open the Trash. */
  onTrash: () => void;
  /** A document is being dragged over the Trash chip. */
  trashDragOver: boolean;
  onTrashDragOver: (e: React.DragEvent) => void;
  onTrashDragLeave: () => void;
  onTrashDrop: (e: React.DragEvent) => void;

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
    <div style={{ position: "relative", flexShrink: 0 }}>
      <button
        data-testid="library-course-switcher"
        className="sapHoverWarmer"
        onClick={() => onOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Choose course"
        style={{
          display: "inline-flex", alignItems: "center", gap: 12, height: 40,
          marginLeft: -12, padding: "0 12px", border: 0, borderRadius: 12,
          background: "transparent", fontFamily: FONT_SERIF, fontSize: 24,
          fontWeight: 600, letterSpacing: "-0.01em", color: "#1A1814",
          whiteSpace: "nowrap", cursor: "pointer",
        }}
      >
        {showDot && (
          <span style={{
            width: 14, height: 14, borderRadius: "50%",
            background: dotColor || "transparent",
            border: dotColor ? "0" : "1.5px dashed #8A8372",
            boxSizing: "border-box", flexShrink: 0,
          }} />
        )}
        {title}
        <Glyph name="chevronDown" size={13} fill="#6F6857" />
      </button>
      {open && (
        <>
          <MenuScrim onClick={() => onOpen(false)} />
          <div role="listbox" style={{
            position: "absolute", left: 0, top: 50, zIndex: 31, width: 280,
            transformOrigin: "top left", animation: closing ? MENU_OUT : MENU_IN,
            ...MENU_SURFACE,
          }}>
            {options.map(o => (
              <React.Fragment key={o.id}>
                {o.trash && <MenuDivider />}
                <button
                  role="option"
                  aria-selected={o.on}
                  className="sapHoverMenu"
                  onClick={o.pick}
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 10px",
                    border: 0, borderRadius: 8, background: o.on ? "#F2F6EE" : "transparent",
                    font: "inherit", textAlign: "left", cursor: "pointer",
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{
                      display: "flex", alignItems: "center", gap: 10,
                      fontSize: 14, lineHeight: "21px", fontWeight: 700,
                    }}>
                      {o.trash ? (
                        // The can, drawn at a size its strokes survive, in the
                        // dot's 9px slot so the label and sub-line stay aligned.
                        <span style={{ position: "relative", width: 9, height: 9, flexShrink: 0 }}>
                          <span style={{ position: "absolute", left: -2, top: -2 }}>
                            <TrashIcon size={13} />
                          </span>
                        </span>
                      ) : (
                        <span style={{
                          width: 9, height: 9, borderRadius: "50%",
                          background: o.color || "transparent",
                          border: o.color ? "0" : "1.5px dashed #8A8372",
                          boxSizing: "border-box", flexShrink: 0,
                        }} />
                      )}
                      {o.id}
                    </span>
                    <span style={{
                      display: "block", paddingLeft: 19, fontSize: 13, color: "#6F6857",
                    }}>{o.sub}</span>
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
    <div style={{ display: "flex", gap: 4 }}>
      <button
        className="sapHoverTint"
        onClick={onRename}
        style={{
          height: 32, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent",
          color: "#445D22", font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
        }}
      >Rename</button>
      <button
        className="sapHoverDanger"
        onClick={onDelete}
        style={{
          height: 32, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent",
          color: "#A8443F", font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
        }}
      >Delete Folder</button>
    </div>
  );
}

/**
 * The Trash, as its own control beside the scope switcher.
 *
 * This is the handoff's `trashBtn` — a chip with a can whose lid tilts when a
 * document is dragged over it, and a drop target that trashes what lands on
 * it. It was briefly folded into the scope switcher as a last option, which
 * cost it both of those: a menu item cannot be a drop target, and the can
 * cannot react to a drag the student is in the middle of. Owner's call
 * 2026-11-26 puts it back out here, where the prototype has it.
 *
 * Without the count the handoff draws (owner's call 2026-11-25), so the label
 * is the chip's only text.
 */
function TrashButton({ active, over, onPick, onOver, onLeave, onDrop }: {
  active: boolean;
  over: boolean;
  onPick: () => void;
  onOver: (e: React.DragEvent) => void;
  onLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}) {
  return (
    <button
      type="button"
      data-testid="library-trash"
      className="sapHoverWarmer"
      onClick={onPick}
      onDragOver={onOver}
      onDragLeave={onLeave}
      onDrop={onDrop}
      aria-pressed={active}
      aria-label="Trash"
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        height: 40, padding: "0 14px", border: 0, borderRadius: 12,
        background: over ? "#DCE8CE" : active ? "#EDE9E0" : "transparent",
        boxShadow: over ? "inset 0 0 0 1.5px #597536" : "none",
        color: "#1A1814", font: "inherit", fontSize: 15,
        fontWeight: active ? 700 : 400,
        whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer",
      }}
    >
      <svg
        width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#6F6857"
        strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true" style={{ display: "block", flexShrink: 0 }}
      >
        {/* The lid is its own group so it can tilt off the can's right edge. */}
        <g style={{
          transformBox: "fill-box", transformOrigin: "85% 100%",
          transform: over ? "rotate(-18deg) translateY(-1px)" : "none",
          transition: "transform 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
        }}>
          <path d="M4 7h16" />
          <path d="M9 7V4.5h6V7" />
        </g>
        <path d="M6 7l1 13h10l1-13" />
        <path d="M10 11v5.5M14 11v5.5" />
      </svg>
      <span>Trash</span>
    </button>
  );
}


/** The 30-day notice and the two-step Empty Trash. */
function EmptyTrash({ confirm, onClick }: { confirm: boolean; onClick: () => void }) {
  return (
    <>
      <span style={{ fontSize: 14, color: "#6F6857" }}>
        Documents in Trash are deleted forever after 30 days.
      </span>
      <button
        data-testid="library-empty-trash"
        onClick={onClick}
        style={{
          height: 36, padding: "0 14px", border: 0, borderRadius: 9,
          background: confirm ? "#A8443F" : "#F1D9D6",
          color: confirm ? "#FFFFFF" : "#A8443F",
          font: "inherit", fontSize: 14, fontWeight: 700,
          whiteSpace: "nowrap", cursor: "pointer",
        }}
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
    onTrash, trashDragOver, onTrashDragOver, onTrashDragLeave, onTrashDrop,
    courseScanLabel, courseScanning, onCourseScan, view, onView,
  } = props;

  return (
    <div style={{
      position: "relative",
      zIndex: 10,
      display: "flex",
      alignItems: "center",
      gap: 12,
      paddingBottom: 14,
      borderBottom: "1px solid rgba(42,39,31,0.10)",
      minHeight: 38,
    }}>
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
          style={{
            height: 36, padding: "0 10px", border: "1.5px solid #597536", borderRadius: 8,
            background: "#FDFCF9", fontFamily: FONT_SERIF, fontSize: 22, fontWeight: 600,
            color: "#1A1814", outline: "none",
          }}
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

      <TrashButton
        active={isTrash}
        over={trashDragOver}
        onPick={onTrash}
        onOver={onTrashDragOver}
        onLeave={onTrashDragLeave}
        onDrop={onTrashDrop}
      />

      {isFolder && !folderRenaming && (
        <FolderActions onRename={onFolderRenameStart} onDelete={onFolderDelete} />
      )}

      <span style={{ flex: 1 }} />

      {courseScanLabel && !isTrash && (
        <button
          data-testid="library-course-scan"
          className="sapHoverTint"
          onClick={onCourseScan}
          disabled={courseScanning}
          title={`Extend the concept graph for ${courseScanLabel}`}
          style={{
            display: "inline-flex", alignItems: "center", gap: 7, height: 36, padding: "0 12px",
            border: "1px solid rgba(42,39,31,0.14)", borderRadius: 9, background: "#FDFCF9",
            color: "#2F4417", font: "inherit", fontSize: 14, fontWeight: 600,
            whiteSpace: "nowrap", cursor: courseScanning ? "default" : "pointer",
            opacity: courseScanning ? 0.7 : 1,
          }}
        >
          <Icon name="sparkle" size={13} />
          {courseScanning ? "Scanning…" : `Scan ${courseScanLabel}`}
        </button>
      )}

      {trashHasItems && (
        <EmptyTrash confirm={emptyConfirm} onClick={onEmptyTrash} />
      )}

      {scoped && (
        <span style={{ fontSize: 14, color: "#3F3B31" }}>
          Searching in {scopeName} ·{" "}
          <button
            onClick={onSearchAll}
            style={{
              border: 0, padding: 0, background: "transparent", color: "#445D22",
              font: "inherit", fontWeight: 700, cursor: "pointer",
              textDecoration: "underline", textUnderlineOffset: 3,
            }}
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
