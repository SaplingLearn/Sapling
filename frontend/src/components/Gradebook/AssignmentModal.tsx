"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

export interface AssignmentDraft {
  title: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
}

interface Props {
  open: boolean;
  initial?: GradedAssignment | null;
  categories: GradeCategory[];
  onClose: () => void;
  onSave: (draft: AssignmentDraft) => Promise<void>;
  onDelete?: (() => Promise<void>) | null;
}

const TYPE_OPTIONS = ["homework", "exam", "quiz", "reading", "project", "other"];

export function AssignmentModal({
  open, initial, categories, onClose, onSave, onDelete,
}: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [draft, setDraft] = React.useState<AssignmentDraft>({
    title: "",
    category_id: null,
    points_possible: null,
    points_earned: null,
    due_date: null,
    assignment_type: null,
    notes: null,
  });
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) {
      setDraft({
        title: initial?.title ?? "",
        category_id: initial?.category_id ?? null,
        points_possible: initial?.points_possible ?? null,
        points_earned: initial?.points_earned ?? null,
        due_date: initial?.due_date ?? null,
        assignment_type: initial?.assignment_type ?? null,
        notes: initial?.notes ?? null,
      });
    }
  }, [open, initial]);

  if (!mounted || !open) return null;

  const valid = draft.title.trim() !== "" &&
    (draft.points_possible === null || draft.points_possible > 0);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)", borderRadius: 12, padding: 20,
          minWidth: 420, maxWidth: 520,
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>
          {initial ? "Edit assignment" : "New assignment"}
        </h3>
        <div style={{ display: "grid", gap: 10 }}>
          <label>
            Title
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
          <label>
            Category
            <select
              value={draft.category_id ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, category_id: e.target.value || null })
              }
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            >
              <option value="">— Uncategorized —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ flex: 1 }}>
              Earned
              <input
                type="number"
                value={draft.points_earned ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    points_earned: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
            </label>
            <label style={{ flex: 1 }}>
              Possible
              <input
                type="number"
                value={draft.points_possible ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    points_possible: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
            </label>
          </div>
          <label>
            Due date
            <input
              type="date"
              value={draft.due_date ?? ""}
              onChange={(e) => setDraft({ ...draft, due_date: e.target.value || null })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
          <label>
            Type
            <select
              value={draft.assignment_type ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, assignment_type: e.target.value || null })
              }
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            >
              <option value="">—</option>
              {TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Notes
            <textarea
              value={draft.notes ?? ""}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value || null })}
              rows={2}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
        </div>
        <div
          style={{
            marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}
        >
          <div>
            {onDelete && initial && (
              <button
                type="button"
                onClick={async () => { await onDelete(); onClose(); }}
                style={{ color: "var(--err)" }}
              >
                Delete
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!valid || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(draft); onClose(); }
                finally { setSaving(false); }
              }}
              style={{
                background: valid ? "var(--accent)" : "var(--bg-soft)",
                color: valid ? "#fff" : "var(--text-dim)",
                border: 0, borderRadius: 6, padding: "6px 14px",
                cursor: valid ? "pointer" : "not-allowed",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
