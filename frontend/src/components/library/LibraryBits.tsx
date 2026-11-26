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
import { FolderIcon, Glyph, MENU_IN, MENU_OUT } from "./primitives";
import { cn } from "@/lib/cn";

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
      className="grid grid-cols-[minmax(0,_1fr)] grid-rows-[1fr]" style={{ ...(moving ? { animation: `sapBulkRow${dir} ${ms}ms ${ease} both` } : null) }}
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
    <div data-testid="library-bulk-bar" className="mt-3 flex items-center gap-2.5 pt-2 pr-2 pb-2 pl-4 bg-[#E6EDDC] text-ink-800 rounded-[12px] relative z-5">
      <span className="font-bold">{count} Selected</span>
      <span className="flex-1" />

      {!isTrash && (
        <div className="relative">
          <button
            className="sapHoverChipOn inline-flex items-center gap-1.5 h-8.5 py-0 px-3 border-0 rounded-[8px] [background:#C9DCB2] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold cursor-pointer"
            onClick={() => onMenu(!menuOpen)}
          >
            Move To
            <Glyph name="chevronDown" size={10} />
          </button>
          {menuOpen && (
            <div data-testid="library-bulk-menu" className="absolute right-0 top-10 w-60 text-ink-800 z-6 max-h-80 overflow-y-auto bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px [transform-origin:top_right]" style={{ animation: menuClosing ? MENU_OUT : MENU_IN }}>
              <span className="pt-1.5 px-2.5 pb-1 font-sans text-md text-text-muted">Course</span>
              {courses.map(c => (
                <button
                  key={c.course_id}
                  className="sapHoverMenu flex items-center gap-2.5 py-2 px-2.5 border-0 rounded-[8px] [background:transparent] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-left cursor-pointer"
                  onClick={() => onMoveCourse(c.course_id)}
                >
                  <span className={cn("w-[9px] h-[9px] rounded-[50%] box-border", c.color ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: c.color || "transparent" }} />
                  {courseLabel(c)} · {c.course_name}
                </button>
              ))}
              <button
                className="sapHoverMenu flex items-center gap-2.5 py-2 px-2.5 border-0 rounded-[8px] [background:transparent] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-left cursor-pointer"
                onClick={() => onMoveCourse(null)}
              >
                <span className="w-[9px] h-[9px] rounded-[50%] bg-transparent border-[1.5px] border-dashed border-ink-400 box-border" />
                No Course
              </button>

              {/* The second group sits a little lower, as the design draws it. */}
              {folders.length > 0 && (
                <span className="font-sans text-md text-text-muted pt-2 px-2.5 pb-1">Folder</span>
              )}
              {folders.map(f => {
                const c = courses.find(x => x.course_id === f.course_id);
                return (
                  <button
                    key={f.id}
                    className="sapHoverMenu flex items-center gap-2.5 py-2 px-2.5 border-0 rounded-[8px] [background:transparent] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base text-left cursor-pointer"
                    onClick={() => onMoveFolder(f.id)}
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
          className="sapHoverChipOn h-8.5 py-0 px-3 border-0 rounded-[8px] [background:#C9DCB2] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-bold whitespace-nowrap cursor-pointer"
          onClick={onRestore}
        >Restore</button>
      )}

      <button
        onClick={onDelete}
        className={cn("h-8.5 py-0 px-3 border-0 rounded-[8px] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold cursor-pointer", deleteConfirm ? "bg-[#A8443F]" : "bg-[#F1D9D6]", deleteConfirm ? "text-accent-fg" : "text-[#A8443F]")}
      >{deleteLabel}</button>

      <button
        onClick={onClear}
        className="h-8.5 py-0 px-3 border-0 rounded-[8px] bg-transparent text-brand-forest [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold cursor-pointer underline [text-underline-offset:3px]"
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
    <div data-testid="library-empty" className="max-w-110 mt-18 mx-auto mb-0 text-center flex flex-col items-center gap-2.5">
      <div className="font-serif text-2xl font-semibold">{title}</div>
      <div className="text-[15px] text-ink-600 text-pretty">{body}</div>
      <div className="flex gap-2.5 mt-1.5">
        {hasQuery && (
          <button
            onClick={onClearSearch}
            className="h-9.5 py-0 px-4 border-[1.5px] border-brand-forest bg-transparent text-brand-forest rounded-md [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
          >Clear Search</button>
        )}
        {scoped && (
          <button
            onClick={onSearchAll}
            className="h-9.5 py-0 px-4 border-0 bg-brand-forest text-accent-fg rounded-md [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
          >Search All Documents</button>
        )}
      </div>
    </div>
  );
}

export function UndoToast({ message, onUndo }: { message: string; onUndo?: () => void }) {
  return (
    <div role="status" data-testid="library-toast" className="absolute left-1/2 bottom-7 [transform:translateX(-50%)] flex items-center gap-4 pt-2.5 pr-2.5 pb-2.5 pl-4.5 bg-ink-800 text-ink-0 rounded-[12px] [box-shadow:0_12px_30px_rgba(25,37,11,0.24)] text-[15px] whitespace-nowrap z-20">
      <span>{message}</span>
      {onUndo && (
        <button
          data-testid="library-toast-undo"
          onClick={onUndo}
          className="h-8 py-0 px-3 border-0 rounded-[8px] bg-[rgba(250,248,243,0.14)] text-leaf-100 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-bold cursor-pointer"
        >Undo</button>
      )}
    </div>
  );
}
