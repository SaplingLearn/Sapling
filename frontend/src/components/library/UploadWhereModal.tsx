"use client";
/**
 * "Where Does This Belong?" — the dialog that picks the course and folder an
 * upload lands in, and then shows it happening.
 *
 * The prototype's modal ends at the picker: its mock upload is instant. A real
 * upload streams for a while and can fail per file, so the same dialog has a
 * second phase — the identical file rows, each carrying its live status —
 * rather than a separate screen. Everything else is the design's literal.
 */
import React from "react";

import type { DocFolder } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import { FMT, FMT_FALLBACK, courseLabel } from "./libraryModel";
import { FolderIcon, Glyph, MENU_IN, MenuScrim } from "./primitives";
import type { UploadRow } from "./useUploadQueue";
import { cn } from "@/lib/cn";

/**
 * Which course a filename suggests, by the words in it. The prototype hard
 * -codes a keyword per mock course; here the student's real course codes and
 * names are the keywords, which is the same idea against real data.
 */
export function guessCourse(files: File[], courses: EnrolledCourse[]): string | null {
  const names = files.map(f => f.name.toLowerCase()).join(" ");
  const compact = names.replace(/\s+/g, "");
  for (const c of courses) {
    const code = courseLabel(c).toLowerCase().replace(/\s+/g, "");
    if (code.length >= 3 && compact.includes(code)) return c.course_id;
  }
  for (const c of courses) {
    const words = (c.course_name || "").toLowerCase().split(/\W+/).filter(w => w.length > 4);
    if (words.some(w => names.includes(w))) return c.course_id;
  }
  return null;
}

export interface UploadWhereModalProps {
  rows: UploadRow[];
  courses: EnrolledCourse[];
  folders: DocFolder[];
  courseId: string | null;
  onCourseId: (id: string | null) => void;
  folderId: string | null;
  onFolderId: (id: string | null) => void;
  /** The course the filenames suggest, named above the picker. */
  suggested: string | null;
  /** The picker is done; the dialog is showing progress. */
  started: boolean;
  busy: boolean;
  finished: boolean;
  onConfirm: () => void;
  onRetry: (id: string) => void;
  onCancelRow: (id: string) => void;
  onClose: () => void;
  /** True while the closing animation plays. */
  closing: boolean;
}

/** One file in the dialog: its tag, its name, and whatever it is doing now. */
function FileRow({
  row, started, onRetry, onCancel,
}: {
  row: UploadRow;
  started: boolean;
  onRetry: (id: string) => void;
  onCancel: (id: string) => void;
}) {
  const note = row.status === "uploading" ? row.progress
    : row.status === "error" ? row.error
      : row.status === "done" ? "Added to your library" : null;
  const noteColor = row.status === "error" ? "#A8443F"
    : row.status === "done" ? "#2F4417" : "#445D22";

  return (
    <div className="flex items-center gap-3 py-2.5 px-3 rounded-md bg-ink-50">
      <span className="w-6.5 h-8 rounded-xs text-accent-fg grid place-items-center box-border font-sans text-[7px] font-semibold leading-none tracking-[0] shrink-0" style={{ background: FMT[row.fmt] || FMT_FALLBACK }}>{row.fmt}</span>

      <span className="flex-1 min-w-0">
        <span className="block text-[15px] font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{row.name}</span>
        {note && (
          <span className="block text-md" style={{ color: noteColor }}>{note}</span>
        )}
      </span>

      {row.status === "error" && (
        <button
          className="sapHoverChip h-7.5 py-0 px-2.5 border-0 rounded-[8px] [background:#DCE8CE] text-leaf-800 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-bold cursor-pointer"
          onClick={() => onRetry(row.id)}
        >Retry</button>
      )}
      {row.status === "uploading" && (
        <button
          className="sapHoverWarmer h-7.5 py-0 px-2.5 border-0 rounded-[8px] [background:transparent] text-text-muted [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-md font-semibold cursor-pointer"
          onClick={() => onCancel(row.id)}
        >Cancel</button>
      )}
      {!started && <span className="text-md text-text-muted">{row.size}</span>}
      {row.status === "done" && <Glyph name="check" size={14} fill="#445D22" />}
    </div>
  );
}

/** The course radio grid, with the filename's suggestion called out. */
function CoursePicker({
  courses, courseId, suggested, onPick,
}: {
  courses: EnrolledCourse[];
  courseId: string | null;
  suggested: string | null;
  onPick: (id: string) => void;
}) {
  const hint = suggested ? courses.find(c => c.course_id === suggested) : undefined;
  return (
    <>
      <div className="flex items-center gap-2.5">
        <span className="font-sans text-base text-text-muted">Course</span>
        {hint && (
          <span className="text-md text-brand-forest font-semibold">
            Sapling suggests {courseLabel(hint)} · {hint.course_name}
          </span>
        )}
      </div>
      <div role="radiogroup" aria-label="Course" className="grid grid-cols-[1fr_1fr] gap-2 max-h-55 overflow-y-auto">
        {courses.map(c => {
          const on = courseId === c.course_id;
          return (
            <button
              key={c.course_id}
              role="radio"
              aria-checked={on}
              data-on={on ? "1" : "0"}
              className={cn("sapUplCourse", "flex items-center gap-2.5 py-3 px-3.5 rounded-[12px] [font:inherit] text-left cursor-pointer", on ? "border-[1.5px] border-brand-forest-bright" : "border-[1.5px] border-[rgba(42,39,31,0.14)]", on ? "[background:#F2F6EE]" : "[background:#FDFCF9]")}
              onClick={() => onPick(c.course_id)}
            >
              <span className={cn("w-2.5 h-2.5 rounded-[50%] box-border shrink-0", c.color ? "border-0" : "border-[1.5px] border-dashed border-ink-400")} style={{ background: c.color || "transparent" }} />
              <span className="flex-1 min-w-0">
                <span className="block text-[15px] font-bold text-ink-800">{courseLabel(c)}</span>
                <span className="block text-md text-text-muted whitespace-nowrap overflow-hidden text-ellipsis">{c.course_name}</span>
              </span>
              {on && <Glyph name="check" size={14} fill="#445D22" />}
            </button>
          );
        })}
      </div>
    </>
  );
}

/** The optional folder dropdown, inert until its course has folders. */
function FolderPicker({
  folders, courseId, folderId, onPick,
}: {
  folders: DocFolder[];
  courseId: string | null;
  folderId: string | null;
  onPick: (id: string | null) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const options = folders.filter(f => (f.course_id || null) === courseId);
  const selected = options.find(f => f.id === folderId);
  const none = options.length === 0;
  const label = none
    ? (courseId ? "No folders in this course" : "Pick a course first")
    : selected ? selected.name : "None";

  return (
    <>
      <span className="mt-3.5 font-sans text-base text-text-muted">
        Folder{" "}
        <span className="font-sans text-md">(optional)</span>
      </span>

      <div className="relative">
        <button
          onClick={() => { if (!none) setOpen(o => !o); }}
          disabled={none}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Folder"
          className={cn("w-full flex items-center gap-2.5 h-11.5 py-0 px-3.5 rounded-[12px] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-[15px] font-semibold text-left", open ? "border-[1.5px] border-brand-forest-bright" : "border-[1.5px] border-[rgba(42,39,31,0.16)]", none ? "bg-ink-50" : "bg-bg-panel", none ? "text-ink-400" : "text-ink-800", none ? "cursor-default" : "cursor-pointer")}
        >
          {selected && <span className="inline-flex"><FolderIcon size={15} /></span>}
          <span className="flex-1 min-w-0 whitespace-nowrap overflow-hidden text-ellipsis">{label}</span>
          <Glyph name="chevronDown" size={11} fill="#6F6857" />
        </button>

        {open && !none && (
          <>
            <MenuScrim onClick={() => setOpen(false)} zIndex={1} />
            <div role="listbox" aria-label="Folder" className="absolute left-0 right-0 bottom-13 z-2 [transform-origin:top_right] bg-bg-panel border border-[rgba(42,39,31,0.14)] rounded-[12px] [box-shadow:0_14px_36px_rgba(25,37,11,0.16)] p-1.5 flex flex-col gap-px" style={{ animation: MENU_IN }}>
              {[{ id: null as string | null, name: "None" }, ...options].map(f => {
                const on = folderId === f.id;
                return (
                  <button
                    key={f.id ?? "none"}
                    role="option"
                    aria-selected={on}
                    className={cn("sapHoverMenu", "flex items-center gap-2.5 py-[9px] px-2.5 border-0 rounded-[8px] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-base font-semibold text-ink-800 text-left cursor-pointer", on ? "[background:#F2F6EE]" : "[background:transparent]")}
                    onClick={() => { onPick(f.id); setOpen(false); }}
                  >
                    {f.id && (
                      <span className="inline-flex"><FolderIcon size={15} /></span>
                    )}
                    <span className="flex-1">{f.name}</span>
                    <Glyph name="check" size={12} fill="#445D22" style={{ opacity: on ? 1 : 0 }} />
                  </button>
                );
              })}
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** Cancel + the CTA while picking; a single Done once the upload is running. */
function ModalFooter({
  started, busy, finished, canConfirm, cta, onConfirm, onClose,
}: {
  started: boolean;
  busy: boolean;
  finished: boolean;
  canConfirm: boolean;
  cta: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  if (started) {
    return (
      <button
        data-testid="library-upload-done"
        className={cn(finished ? "sapHoverForest" : "sapHoverWarm", "h-11.5 py-0 px-5.5 border-0 rounded-[11px] [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-[15px] font-bold", finished ? "[background:#445D22]" : "[background:transparent]", finished ? "text-accent-fg" : "text-ink-600", busy ? "cursor-default" : "cursor-pointer", busy ? "opacity-60" : "opacity-100")}
        onClick={onClose}
        disabled={busy}
      >{busy ? "Working…" : "Done"}</button>
    );
  }
  return (
    <>
      <button
        className="sapHoverWarm h-11.5 py-0 px-4.5 border-0 rounded-[11px] [background:transparent] text-ink-600 [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-[15px] font-bold cursor-pointer"
        onClick={onClose}
      >Cancel</button>
      <button
        data-testid="library-upload-confirm"
        className={cn("sapHoverForest", "h-11.5 py-0 px-5.5 border-0 rounded-[11px] [background:#445D22] text-accent-fg [font-family:inherit] [font-style:inherit] [font-variant:inherit] [font-stretch:inherit] [line-height:inherit] text-[15px] font-bold", canConfirm ? "cursor-pointer" : "cursor-not-allowed", canConfirm ? "opacity-100" : "opacity-50")}
        onClick={onConfirm}
        disabled={!canConfirm}
      >{cta}</button>
    </>
  );
}

export function UploadWhereModal(props: UploadWhereModalProps) {
  const {
    rows, courses, folders, courseId, onCourseId, folderId, onFolderId, suggested,
    started, busy, finished, onConfirm, onRetry, onCancelRow, onClose, closing,
  } = props;

  const n = rows.length;
  const heading = started ? (busy ? "Reading Your Documents" : "Done") : "Where Does This Belong?";
  const subtitle = started
    ? "Sapling reads each file, summarizes it, and links it to your concepts."
    : n === 1
      ? "Pick a course so Sapling can link this document to the right concepts."
      : `Pick a course for these ${n} documents so Sapling can link them to the right concepts.`;

  return (
    <div className={cn("absolute inset-0 z-50 bg-[rgba(26,24,20,0.32)] grid place-items-center", closing ? "[animation:sapScrimOut_180ms_ease_both]" : "[animation:sapScrimIn_200ms_ease_both]")}>
      {/* Clicking away cancels the picker, but never a running upload. */}
      <div onClick={busy ? undefined : onClose} className="absolute inset-0" />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Choose where the upload belongs"
        data-testid="library-upload-where"
        className={cn("relative w-160 max-h-215 flex flex-col bg-bg-panel rounded-[18px] [box-shadow:0_24px_64px_rgba(25,37,11,0.28)] overflow-hidden", closing ? "[animation:sapModalOut_160ms_cubic-bezier(0.4,_0,_1,_1)_both]" : "[animation:sapModalIn_240ms_cubic-bezier(0.2,_0.7,_0.2,_1)_both]")}
      >
        <div className="pt-7 px-8 pb-5 flex flex-col gap-1.5">
          <h2 className="m-0 font-serif text-[28px] font-semibold tracking-[-0.015em] text-ink-800">{heading}</h2>
          <p className="m-0 text-[15px] text-ink-600">{subtitle}</p>
        </div>

        <div className="py-0 px-8 flex flex-col gap-2 overflow-y-auto">
          {rows.map(r => (
            <FileRow
              key={r.id}
              row={r}
              started={started}
              onRetry={onRetry}
              onCancel={onCancelRow}
            />
          ))}
        </div>

        {!started && (
          <div className="pt-6 px-8 pb-2 flex flex-col gap-2.5">
            <CoursePicker
              courses={courses}
              courseId={courseId}
              suggested={suggested}
              onPick={id => { onCourseId(id); onFolderId(null); }}
            />
            <FolderPicker
              folders={folders}
              courseId={courseId}
              folderId={folderId}
              onPick={onFolderId}
            />
          </div>
        )}

        <div className="pt-5 px-8 pb-7 flex items-center justify-end gap-2.5">
          <ModalFooter
            started={started}
            busy={busy}
            finished={finished}
            canConfirm={!!courseId}
            cta={n === 1 ? "Add to Library" : `Add ${n} to Library`}
            onConfirm={onConfirm}
            onClose={onClose}
          />
        </div>
      </div>
    </div>
  );
}
