"use client";
/**
 * The three small regions the Library shows around its list: the bulk-action
 * bar, the empty state, and the undo toast.
 */
import React from "react";

import type { DocFolder } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";
import { courseLabel } from "./libraryModel";
import {
  FolderIcon, Glyph, MENU_HEADING, MENU_SURFACE,
} from "./primitives";

export interface BulkBarProps {
  count: number;
  isTrash: boolean;
  menuOpen: boolean;
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
    count, isTrash, menuOpen, onMenu, courses, folders, onMoveCourse, onMoveFolder,
    onRestore, onDelete, deleteConfirm, onClear,
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
            <div style={{
              position: "absolute", right: 0, top: 40, width: 240, color: "#1A1814",
              zIndex: 6, maxHeight: 320, overflowY: "auto", ...MENU_SURFACE,
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
