"use client";
/**
 * The three small regions the Library shows around its list: the bulk-action
 * bar (and the reveal that animates it in and out), the empty state, and the
 * undo toast.
 */
import React from "react";

import type { DocFolder } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import { courseLabel } from "./libraryModel";
import {
  FolderIcon, Glyph, MENU_HEADING, MENU_IN, MENU_OUT, MENU_SURFACE,
} from "./primitives";

/**
 * The selection bar's entrance and exit. The same curves the Library already
 * uses: the 0.2/0.7 ease-out every entrance runs on, and the ease-in its exits
 * (`sapRowOut`, `sapModalOut`, `sapMenuOut`) leave on. The timers below match
 * the keyframes, so the bar is unmounted the moment its exit finishes.
 */
export const BULK_IN_MS = 220;
export const BULK_OUT_MS = 160;
const BULK_IN_EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";
const BULK_OUT_EASE = "cubic-bezier(0.4, 0, 1, 1)";

/** `in` and `out` are animating; `idle` is the bar at rest, with no animation. */
export type RevealPhase = "in" | "idle" | "out";

/**
 * Keeps the selection bar on screen through its exit, and opens and closes the
 * row it sits in so the list below glides rather than jumps.
 *
 * Two wrappers, both inert at rest: the outer is a one-row grid whose track
 * tweens 0fr <-> 1fr (`sapBulkRow*`), the inner clips the bar while the track
 * is short and fades/drops it (`sapBulk*`). At rest the animation and the clip
 * are removed, so the bar's look, position and spacing are exactly the bar
 * alone — and the Move To menu can hang below it unclipped.
 *
 * While the bar leaves it shows what it showed last ("2 Selected"), not the
 * cleared selection. A count change while open re-renders the same element
 * with the same animation, so it never replays the entrance. Reduced motion is
 * the Library's own rule in library-notes.css: every animation under
 * `[data-sap-surface]` runs for 1ms, so both ends snap.
 */
export function BulkBarReveal({ open, children }: { open: boolean; children: React.ReactNode }) {
  const [phase, setPhase] = React.useState<RevealPhase | null>(open ? "in" : null);
  const [wasOpen, setWasOpen] = React.useState(open);
  const [held, setHeld] = React.useState<React.ReactNode>(open ? children : null);

  // React's "adjust state when a prop changes" pattern: no extra commit, so
  // the frame the selection clears already renders the exit, never a gap.
  if (open !== wasOpen) {
    setWasOpen(open);
    setPhase(open ? "in" : "out");
  }
  if (open && held !== children) setHeld(children);

  React.useEffect(() => {
    if (phase === "in") {
      const t = setTimeout(() => setPhase("idle"), BULK_IN_MS);
      return () => clearTimeout(t);
    }
    if (phase === "out") {
      const t = setTimeout(() => { setPhase(null); setHeld(null); }, BULK_OUT_MS);
      return () => clearTimeout(t);
    }
  }, [phase]);

  if (phase === null) return null;
  const moving = phase !== "idle";
  const [ms, ease] = phase === "out" ? [BULK_OUT_MS, BULK_OUT_EASE] : [BULK_IN_MS, BULK_IN_EASE];
  const dir = phase === "out" ? "Out" : "In";
  return (
    <div
      data-testid="library-bulk-reveal"
      data-phase={phase}
      style={{
        // The column is the full width, as the bar alone was (LibraryBody's
        // stack sizes its grid the same way).
        display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gridTemplateRows: "1fr",
        ...(moving ? { animation: `sapBulkRow${dir} ${ms}ms ${ease} both` } : null),
      }}
    >
      {/* The clip is what lets the row close past the bar's own height; a
          clipping grid item may shrink to 0, so no min-height is needed. */}
      <div style={{
        ...(moving ? {
          overflow: "hidden", transformOrigin: "50% 0",
          animation: `sapBulk${dir} ${ms}ms ${ease} both`,
        } : null),
        ...(phase === "out" ? { pointerEvents: "none" as const } : null),
      }}>
        {open ? children : held}
      </div>
    </div>
  );
}

export interface BulkBarProps {
  count: number;
  isTrash: boolean;
  menuOpen: boolean;
  /** The Move To menu is playing its exit, as every Library menu does. */
  menuClosing?: boolean;
  onMenu: (open: boolean) => void;
  courses: EnrolledCourse[];
  folders: DocFolder[];
  onMoveCourse: (id: string | null) => void;
  onMoveFolder: (id: string) => void;
  onRestore: () => void;
  onDelete: () => void;
  deleteConfirm: boolean;
  onClear: () => void;
}

export function BulkBar(props: BulkBarProps) {
  const {
    count, isTrash, menuOpen, menuClosing = false, onMenu, courses, folders,
    onMoveCourse, onMoveFolder, onRestore, onDelete, deleteConfirm, onClear,
  } = props;

  const deleteLabel = isTrash
    ? (deleteConfirm ? "Click Again to Delete Forever" : "Delete Forever")
    : deleteConfirm ? "Click Again to Delete" : "Move to Trash";

  return (
    <div data-testid="library-bulk-bar" style={{
      marginTop: 12, display: "flex", alignItems: "center", gap: 10,
      padding: "8px 8px 8px 16px", background: "#E6EDDC", color: "#1A1814",
      borderRadius: 12, position: "relative", zIndex: 5,
    }}>
      <span style={{ fontWeight: 700 }}>{count} Selected</span>
      <span style={{ flex: 1 }} />

      {!isTrash && (
        <div style={{ position: "relative" }}>
          <button
            className="sapHoverChipOn"
            onClick={() => onMenu(!menuOpen)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6, height: 34, padding: "0 12px",
              border: 0, borderRadius: 8, background: "#C9DCB2", color: "#2F4417",
              font: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
            }}
          >
            Move To
            <Glyph name="chevronDown" size={10} />
          </button>
          {menuOpen && (
            <div data-testid="library-bulk-menu" style={{
              position: "absolute", right: 0, top: 40, width: 240, color: "#1A1814",
              zIndex: 6, maxHeight: 320, overflowY: "auto", ...MENU_SURFACE,
              // It hangs from the Move To button, so it grows from that corner.
              transformOrigin: "top right", animation: menuClosing ? MENU_OUT : MENU_IN,
            }}>
              <span style={MENU_HEADING}>Course</span>
              {courses.map(c => (
                <button
                  key={c.course_id}
                  className="sapHoverMenu"
                  onClick={() => onMoveCourse(c.course_id)}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
                    border: 0, borderRadius: 8, background: "transparent", font: "inherit",
                    fontSize: 14, textAlign: "left", cursor: "pointer",
                  }}
                >
                  <span style={{
                    width: 9, height: 9, borderRadius: "50%",
                    background: c.color || "transparent",
                    border: c.color ? "0" : "1.5px dashed #8A8372", boxSizing: "border-box",
                  }} />
                  {courseLabel(c)} · {c.course_name}
                </button>
              ))}
              <button
                className="sapHoverMenu"
                onClick={() => onMoveCourse(null)}
                style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
                  border: 0, borderRadius: 8, background: "transparent", font: "inherit",
                  fontSize: 14, textAlign: "left", cursor: "pointer",
                }}
              >
                <span style={{
                  width: 9, height: 9, borderRadius: "50%", background: "transparent",
                  border: "1.5px dashed #8A8372", boxSizing: "border-box",
                }} />
                No Course
              </button>

              {/* The second group sits a little lower, as the design draws it. */}
              {folders.length > 0 && (
                <span style={{ ...MENU_HEADING, padding: "8px 10px 4px" }}>Folder</span>
              )}
              {folders.map(f => {
                const c = courses.find(x => x.course_id === f.course_id);
                return (
                  <button
                    key={f.id}
                    className="sapHoverMenu"
                    onClick={() => onMoveFolder(f.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
                      border: 0, borderRadius: 8, background: "transparent", font: "inherit",
                      fontSize: 14, textAlign: "left", cursor: "pointer",
                    }}
                  >
                    <FolderIcon size={14} />
                    {c ? `${courseLabel(c)} / ${f.name}` : f.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {isTrash && (
        <button
          className="sapHoverChipOn"
          onClick={onRestore}
          style={{
            height: 34, padding: "0 12px", border: 0, borderRadius: 8, background: "#C9DCB2",
            color: "#2F4417", font: "inherit", fontSize: 13, fontWeight: 700,
            whiteSpace: "nowrap", cursor: "pointer",
          }}
        >Restore</button>
      )}

      <button
        onClick={onDelete}
        style={{
          height: 34, padding: "0 12px", border: 0, borderRadius: 8,
          background: deleteConfirm ? "#A8443F" : "#F1D9D6",
          color: deleteConfirm ? "#FFFFFF" : "#A8443F",
          font: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
        }}
      >{deleteLabel}</button>

      <button
        onClick={onClear}
        style={{
          height: 34, padding: "0 12px", border: 0, borderRadius: 8, background: "transparent",
          color: "#445D22", font: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
          textDecoration: "underline", textUnderlineOffset: 3,
        }}
      >Clear</button>
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  body: string;
  hasQuery: boolean;
  scoped: boolean;
  onClearSearch: () => void;
  onSearchAll: () => void;
}

export function EmptyState({
  title, body, hasQuery, scoped, onClearSearch, onSearchAll,
}: EmptyStateProps) {
  return (
    <div data-testid="library-empty" style={{
      maxWidth: 440, margin: "72px auto 0", textAlign: "center", display: "flex",
      flexDirection: "column", alignItems: "center", gap: 10,
    }}>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600 }}>{title}</div>
      <div style={{ fontSize: 15, color: "#3F3B31", textWrap: "pretty" }}>{body}</div>
      <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
        {hasQuery && (
          <button
            onClick={onClearSearch}
            style={{
              height: 38, padding: "0 16px", border: "1.5px solid #445D22",
              background: "transparent", color: "#445D22", borderRadius: 10,
              font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
            }}
          >Clear Search</button>
        )}
        {scoped && (
          <button
            onClick={onSearchAll}
            style={{
              height: 38, padding: "0 16px", border: 0, background: "#445D22",
              color: "#FFFFFF", borderRadius: 10, font: "inherit", fontSize: 14,
              fontWeight: 700, cursor: "pointer",
            }}
          >Search All Documents</button>
        )}
      </div>
    </div>
  );
}

export function UndoToast({ message, onUndo }: { message: string; onUndo?: () => void }) {
  return (
    <div role="status" data-testid="library-toast" style={{
      position: "absolute", left: "50%", bottom: 28, transform: "translateX(-50%)",
      display: "flex", alignItems: "center", gap: 16, padding: "10px 10px 10px 18px",
      background: "#1A1814", color: "#FAF8F3", borderRadius: 12,
      boxShadow: "0 12px 30px rgba(25,37,11,0.24)", fontSize: 15,
      whiteSpace: "nowrap", zIndex: 20,
    }}>
      <span>{message}</span>
      {onUndo && (
        <button
          data-testid="library-toast-undo"
          onClick={onUndo}
          style={{
            height: 32, padding: "0 12px", border: 0, borderRadius: 8,
            background: "rgba(250,248,243,0.14)", color: "#D9E7C4",
            font: "inherit", fontSize: 14, fontWeight: 700, cursor: "pointer",
          }}
        >Undo</button>
      )}
    </div>
  );
}
