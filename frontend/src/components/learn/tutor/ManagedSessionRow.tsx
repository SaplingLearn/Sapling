"use client";
import React, { useRef, useState } from "react";
import { useConfirm } from "@/lib/useConfirm";
import type { TutorSessionRow } from "./sessions";
import styles from "./tutor.module.css";

/**
 * One row of every session (wireframe T3) that the student can rename and
 * delete (#866 K31: what the legacy Learn screen's recent sessions offer).
 * `children` is the row's own content (its dot, name, date and status) inside
 * the button that opens it. Rename edits the name in place — Enter or leaving
 * the field saves, Escape keeps it; Delete asks once more before it deletes.
 */
export function ManagedSessionRow({ row, title, onOpen, onRename, onDelete, children }: {
  row: TutorSessionRow;
  /** The name the list shows (a course-wide session reads "Guided session"). */
  title: string;
  onOpen: (row: TutorSessionRow) => void;
  onRename: (row: TutorSessionRow, topic: string) => void;
  onDelete: (row: TutorSessionRow) => void;
  children: React.ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  // Enter or Escape ends the edit and unmounts the field, which can fire its
  // blur: an edit is settled once, so that blur neither saves nor saves twice.
  const settled = useRef(true);
  const del = useConfirm(() => onDelete(row), 3000);
  const finish = (keep: boolean) => {
    if (settled.current) return;
    settled.current = true;
    setEditing(false);
    const next = draft.trim();
    if (keep && next && next !== title) onRename(row, next);
  };
  return (
    <div className={styles.sessionRow} data-testid={`tutor-session-row-${row.id}`}>
      {editing ? (
        <input
          autoFocus
          aria-label="Session name"
          data-testid={`tutor-session-name-${row.id}`}
          className={styles.renameInput}
          value={draft}
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => finish(true)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" && e.key !== "Escape") return;
            e.preventDefault();
            finish(e.key === "Enter");
          }}
        />
      ) : (
        <button type="button" className={styles.listRow} onClick={() => onOpen(row)}>{children}</button>
      )}
      <div className={styles.rowActs}>
        <button type="button" className="btn btn--sm btn--ghost" data-testid={`tutor-session-rename-${row.id}`}
          aria-label={`Rename “${title}”`} disabled={editing}
          onClick={() => { settled.current = false; setDraft(title); setEditing(true); }}>
          Rename
        </button>
        <button type="button" className={del.armed ? "btn btn--sm btn--danger" : "btn btn--sm btn--ghost"}
          data-testid={`tutor-session-delete-${row.id}`} aria-label={del.armed ? `Confirm delete “${title}”` : `Delete “${title}”`}
          onClick={del.trigger}>
          {del.armed ? "Confirm delete" : "Delete"}
        </button>
      </div>
    </div>
  );
}
