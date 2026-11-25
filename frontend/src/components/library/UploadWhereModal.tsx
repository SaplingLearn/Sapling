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
import {
  FolderIcon, FONT_MONO, FONT_SERIF, Glyph, MENU_IN, MENU_SURFACE, MenuScrim,
} from "./primitives";
import type { UploadRow } from "./useUploadQueue";

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
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
      borderRadius: 10, background: "#F4F1EA",
    }}>
      <span style={{
        width: 26, height: 32, borderRadius: 4, background: FMT[row.fmt] || FMT_FALLBACK,
        color: "#FFFFFF", display: "grid", placeItems: "center", boxSizing: "border-box",
        fontFamily: FONT_MONO, fontSize: 7, fontWeight: 600, lineHeight: 1,
        letterSpacing: 0, flexShrink: 0,
      }}>{row.fmt}</span>

      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{
          display: "block", fontSize: 15, fontWeight: 600, whiteSpace: "nowrap",
          overflow: "hidden", textOverflow: "ellipsis",
        }}>{row.name}</span>
        {note && (
          <span style={{ display: "block", fontSize: 13, color: noteColor }}>{note}</span>
        )}
      </span>

      {row.status === "error" && (
        <button
          className="sapHoverChip"
          onClick={() => onRetry(row.id)}
          style={{
            height: 30, padding: "0 10px", border: 0, borderRadius: 8,
            background: "#DCE8CE", color: "#2F4417", font: "inherit", fontSize: 13,
            fontWeight: 700, cursor: "pointer",
          }}
        >Retry</button>
      )}
      {row.status === "uploading" && (
        <button
          className="sapHoverWarmer"
          onClick={() => onCancel(row.id)}
          style={{
            height: 30, padding: "0 10px", border: 0, borderRadius: 8,
            background: "transparent", color: "#6F6857", font: "inherit", fontSize: 13,
            fontWeight: 600, cursor: "pointer",
          }}
        >Cancel</button>
      )}
      {!started && <span style={{ fontSize: 13, color: "#6F6857" }}>{row.size}</span>}
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
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          fontFamily: FONT_MONO, fontSize: 14, color: "#6F6857",
        }}>Course</span>
        {hint && (
          <span style={{ fontSize: 13, color: "#445D22", fontWeight: 600 }}>
            Sapling suggests {courseLabel(hint)} · {hint.course_name}
          </span>
        )}
      </div>
      <div role="radiogroup" aria-label="Course" style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8,
        maxHeight: 220, overflowY: "auto",
      }}>
        {courses.map(c => {
          const on = courseId === c.course_id;
          return (
            <button
              key={c.course_id}
              role="radio"
              aria-checked={on}
              data-on={on ? "1" : "0"}
              className="sapUplCourse"
              onClick={() => onPick(c.course_id)}
              style={{
                display: "flex", alignItems: "center", gap: 10, padding: "12px 14px",
                border: `1.5px solid ${on ? "#597536" : "rgba(42,39,31,0.14)"}`,
                borderRadius: 12, background: on ? "#F2F6EE" : "#FDFCF9",
                font: "inherit", textAlign: "left", cursor: "pointer",
              }}
            >
              <span style={{
                width: 10, height: 10, borderRadius: "50%",
                background: c.color || "transparent",
                border: c.color ? "0" : "1.5px dashed #8A8372",
                boxSizing: "border-box", flexShrink: 0,
              }} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{
                  display: "block", fontSize: 15, fontWeight: 700, color: "#1A1814",
                }}>{courseLabel(c)}</span>
                <span style={{
                  display: "block", fontSize: 13, color: "#6F6857",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{c.course_name}</span>
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
      <span style={{
        marginTop: 14, fontFamily: FONT_MONO, fontSize: 14, color: "#6F6857",
      }}>
        Folder{" "}
        <span style={{ fontFamily: "var(--font-sans)", fontSize: 13 }}>(optional)</span>
      </span>

      <div style={{ position: "relative" }}>
        <button
          onClick={() => { if (!none) setOpen(o => !o); }}
          disabled={none}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label="Folder"
          style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10, height: 46,
            padding: "0 14px",
            border: `1.5px solid ${open ? "#597536" : "rgba(42,39,31,0.16)"}`,
            borderRadius: 12, background: none ? "#F4F1EA" : "#FDFCF9",
            font: "inherit", fontSize: 15, fontWeight: 600,
            color: none ? "#8A8372" : "#1A1814",
            textAlign: "left", cursor: none ? "default" : "pointer",
          }}
        >
          {selected && <span style={{ display: "inline-flex" }}><FolderIcon size={15} /></span>}
          <span style={{
            flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden",
            textOverflow: "ellipsis",
          }}>{label}</span>
          <Glyph name="chevronDown" size={11} fill="#6F6857" />
        </button>

        {open && !none && (
          <>
            <MenuScrim onClick={() => setOpen(false)} zIndex={1} />
            <div role="listbox" aria-label="Folder" style={{
              position: "absolute", left: 0, right: 0, bottom: 52, zIndex: 2,
              transformOrigin: "top right", animation: MENU_IN, ...MENU_SURFACE,
            }}>
              {[{ id: null as string | null, name: "None" }, ...options].map(f => {
                const on = folderId === f.id;
                return (
                  <button
                    key={f.id ?? "none"}
                    role="option"
                    aria-selected={on}
                    className="sapHoverMenu"
                    onClick={() => { onPick(f.id); setOpen(false); }}
                    style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "9px 10px",
                      border: 0, borderRadius: 8, background: on ? "#F2F6EE" : "transparent",
                      font: "inherit", fontSize: 14, fontWeight: 600, color: "#1A1814",
                      textAlign: "left", cursor: "pointer",
                    }}
                  >
                    {f.id && (
                      <span style={{ display: "inline-flex" }}><FolderIcon size={15} /></span>
                    )}
                    <span style={{ flex: 1 }}>{f.name}</span>
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
        className={finished ? "sapHoverForest" : "sapHoverWarm"}
        onClick={onClose}
        disabled={busy}
        style={{
          height: 46, padding: "0 22px", border: 0, borderRadius: 11,
          background: finished ? "#445D22" : "transparent",
          color: finished ? "#FFFFFF" : "#3F3B31",
          font: "inherit", fontSize: 15, fontWeight: 700,
          cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
        }}
      >{busy ? "Working…" : "Done"}</button>
    );
  }
  return (
    <>
      <button
        className="sapHoverWarm"
        onClick={onClose}
        style={{
          height: 46, padding: "0 18px", border: 0, borderRadius: 11,
          background: "transparent", color: "#3F3B31", font: "inherit", fontSize: 15,
          fontWeight: 700, cursor: "pointer",
        }}
      >Cancel</button>
      <button
        data-testid="library-upload-confirm"
        className="sapHoverForest"
        onClick={onConfirm}
        disabled={!canConfirm}
        style={{
          height: 46, padding: "0 22px", border: 0, borderRadius: 11,
          background: "#445D22", color: "#FFFFFF", font: "inherit", fontSize: 15,
          fontWeight: 700, cursor: canConfirm ? "pointer" : "not-allowed",
          opacity: canConfirm ? 1 : 0.5,
        }}
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
    <div style={{
      position: "absolute", inset: 0, zIndex: 50, background: "rgba(26,24,20,0.32)",
      display: "grid", placeItems: "center",
      animation: closing ? "sapScrimOut 180ms ease both" : "sapScrimIn 200ms ease both",
    }}>
      {/* Clicking away cancels the picker, but never a running upload. */}
      <div onClick={busy ? undefined : onClose} style={{ position: "absolute", inset: 0 }} />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Choose where the upload belongs"
        data-testid="library-upload-where"
        style={{
          animation: closing
            ? "sapModalOut 160ms cubic-bezier(0.4, 0, 1, 1) both"
            : "sapModalIn 240ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
          position: "relative", width: 640, maxHeight: 860, display: "flex",
          flexDirection: "column", background: "#FDFCF9", borderRadius: 18,
          boxShadow: "0 24px 64px rgba(25,37,11,0.28)", overflow: "hidden",
        }}
      >
        <div style={{
          padding: "28px 32px 20px", display: "flex", flexDirection: "column", gap: 6,
        }}>
          <h2 style={{
            margin: 0, fontFamily: FONT_SERIF, fontSize: 28, fontWeight: 600,
            letterSpacing: "-0.015em", color: "#1A1814",
          }}>{heading}</h2>
          <p style={{ margin: 0, fontSize: 15, color: "#3F3B31" }}>{subtitle}</p>
        </div>

        <div style={{
          padding: "0 32px", display: "flex", flexDirection: "column", gap: 8,
          overflowY: "auto",
        }}>
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
          <div style={{
            padding: "24px 32px 8px", display: "flex", flexDirection: "column", gap: 10,
          }}>
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

        <div style={{
          padding: "20px 32px 28px", display: "flex", alignItems: "center",
          justifyContent: "flex-end", gap: 10,
        }}>
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
