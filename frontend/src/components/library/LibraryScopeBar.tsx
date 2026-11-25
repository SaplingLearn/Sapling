"use client";
/**
 * The filter row under the header: which scope is open (the course switcher),
 * the Trash, the folder's own Rename / Delete, the notices that belong to a
 * scope, and the List / Panel toggle.
 *
 * The "Scan <COURSE>" button is the old Library's course-wide concept scan,
 * kept and moved here — it is the one control that only makes sense while a
 * single course is open, which is exactly this row's subject.
 */
import React from "react";
import Link from "next/link";

import { Icon } from "../Icon";
import { Glyph as ToolGlyph, TOOL } from "../study/hubUi";
import { studyGuideHref } from "@/lib/toolHrefs";
import {
  FONT_MONO, FONT_SERIF, Glyph, MENU_IN, MENU_OUT, MENU_SURFACE, MenuScrim, TrashIcon,
} from "./primitives";

export interface ScopeOption {
  /** "All Documents", a course code, or "No Course". */
  id: string;
  /** "Every course · 14 documents" */
  sub: string;
  color: string | null;
  on: boolean;
  pick: () => void;
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
  trashCount: number;
  trashDropOver: boolean;
  /** Replays each time something lands in the Trash, so the can bumps. */
  trashBump: number;
  onTrash: () => void;
  onTrashDragOver: (e: React.DragEvent) => void;
  onTrashDragLeave: () => void;
  onTrashDrop: (e: React.DragEvent) => void;

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

/** The Trash button: a drop target, with the lid tilt and the landing bump. */
function TrashButton({
  isTrash, count, dropOver, bump, onClick, onDragOver, onDragLeave, onDrop,
}: {
  isTrash: boolean;
  count: number;
  dropOver: boolean;
  bump: number;
  onClick: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}) {
  // Two keyframe names, alternated, so a second drop restarts the animation
  // instead of being ignored as "already running".
  const suffix = bump % 2 ? "A" : "B";
  return (
    <button
      data-testid="library-trash"
      className="sapHoverWarmer"
      onClick={onClick}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      aria-pressed={isTrash}
      aria-label="Trash"
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, height: 40,
        padding: "0 14px", border: 0, borderRadius: 12,
        background: dropOver ? "#F6E3E1" : isTrash ? "#EBF0E1" : "transparent",
        boxShadow: dropOver
          ? "inset 0 0 0 1.5px #A8443F"
          : isTrash ? "inset 0 0 0 1px rgba(68,93,34,0.22)" : "none",
        color: "#1A1814", font: "inherit", fontSize: 15,
        fontWeight: isTrash ? 700 : 500, whiteSpace: "nowrap", flexShrink: 0,
        cursor: "pointer",
      }}
    >
      <TrashIcon
        size={17}
        lidTransform={dropOver ? "translateY(-2px) rotate(-16deg)" : "none"}
        lidAnimation={bump ? `sapLid${suffix} 520ms cubic-bezier(0.2, 0.7, 0.2, 1)` : "none"}
      />
      <span style={{ display: "inline-flex", alignItems: "baseline", gap: 7, lineHeight: 1 }}>
        <span>Trash</span>
        <span style={{
          fontFamily: FONT_MONO, fontSize: 13, lineHeight: 1, color: "#6F6857",
          transform: "translateY(0.5px)", display: "inline-block",
          animation: bump ? `sapBump${suffix} 420ms cubic-bezier(0.2, 0.7, 0.2, 1)` : "none",
        }}>{count}</span>
      </span>
    </button>
  );
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
              <button
                key={o.id}
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
                    <span style={{
                      width: 9, height: 9, borderRadius: "50%",
                      background: o.color || "transparent",
                      border: o.color ? "0" : "1.5px dashed #8A8372",
                      boxSizing: "border-box", flexShrink: 0,
                    }} />
                    {o.id}
                  </span>
                  <span style={{
                    display: "block", paddingLeft: 19, fontSize: 13, color: "#6F6857",
                  }}>{o.sub}</span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The way out to the Study Guides hub.
 *
 * The guides used to be listed inline above the documents; the hub owns that
 * list, and the design handoff has no guides section at all (it knows "Study
 * Guide" only as a document category). This is the Study hub's own tool
 * button — same `TOOL.guide` tint, same `Glyph`, same `btn btn--sm` with
 * `.tool`'s three overrides — so the two cannot drift apart.
 *
 * It sits at the right of the scope bar, with the view toggle, rather than on
 * the left beside Trash: that left group names WHICH documents the list shows
 * (All Documents, a course, a folder, Trash), and this is not a scope. The
 * right group is where the row's own controls live.
 */
function GuidesButton() {
  const tool = TOOL.guide;
  return (
    <Link
      href={studyGuideHref()}
      data-testid="library-guides"
      className="btn btn--sm"
      style={{
        height: 40, padding: "0 16px", fontSize: "var(--fs-md)",
        whiteSpace: "nowrap", flexShrink: 0, textDecoration: "none",
      }}
    >
      <span aria-hidden="true" style={{ display: "grid", color: tool.fg }}>
        <ToolGlyph name={tool.icon} size={14} />
      </span>
      {tool.title}
    </Link>
  );
}

/** List ⇄ Panel. */
function ViewToggle({
  view, onView,
}: {
  view: "list" | "panel";
  onView: (v: "list" | "panel") => void;
}) {
  const tab = (key: "list" | "panel", label: string, icon: React.ReactNode) => (
    <button
      role="tab"
      data-testid={`library-view-${key}`}
      aria-selected={view === key}
      onClick={() => onView(key)}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7, border: 0, padding: "0 14px",
        borderRadius: 9, font: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
        background: view === key ? "#FDFCF9" : "transparent",
        color: view === key ? "#1A1814" : "#6F6857",
        boxShadow: view === key ? "0 1px 2px rgba(25,37,11,0.10)" : "none",
      }}
    >
      {icon}
      {label}
    </button>
  );
  return (
    <div role="tablist" aria-label="Layout" style={{
      display: "flex", gap: 2, marginLeft: 16, padding: 4, height: 40, flexShrink: 0,
      boxSizing: "border-box", background: "#F4F1EA", borderRadius: 12,
    }}>
      {tab("list", "List", (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <rect x="1" y="2" width="14" height="2.4" rx="1" />
          <rect x="1" y="6.8" width="14" height="2.4" rx="1" />
          <rect x="1" y="11.6" width="14" height="2.4" rx="1" />
        </svg>
      ))}
      {tab("panel", "Panel", (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <rect x="1" y="1" width="6" height="6" rx="1.4" />
          <rect x="9" y="1" width="6" height="6" rx="1.4" />
          <rect x="1" y="9" width="6" height="6" rx="1.4" />
          <rect x="9" y="9" width="6" height="6" rx="1.4" />
        </svg>
      ))}
    </div>
  );
}

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
    isTrash, trashCount, trashDropOver, trashBump, onTrash, onTrashDragOver,
    onTrashDragLeave, onTrashDrop, isFolder, folderRenaming, folderDraft, onFolderDraft,
    onFolderRenameStart, onFolderRenameCommit, onFolderRenameCancel, onFolderDelete,
    trashHasItems, emptyConfirm, onEmptyTrash, scoped, scopeName, onSearchAll,
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
        <>
          <ScopeSwitcher
            title={title}
            dotColor={dotColor}
            showDot={showDot}
            open={courseMenuOpen}
            onOpen={onCourseMenu}
            closing={menuClosing}
            options={scopeOptions}
          />
          <TrashButton
            isTrash={isTrash}
            count={trashCount}
            dropOver={trashDropOver}
            bump={trashBump}
            onClick={onTrash}
            onDragOver={onTrashDragOver}
            onDragLeave={onTrashDragLeave}
            onDrop={onTrashDrop}
          />
        </>
      )}

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

      {!isTrash && <GuidesButton />}
      <ViewToggle view={view} onView={onView} />
    </div>
  );
}
