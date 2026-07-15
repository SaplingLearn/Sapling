"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradedAssignment, GradeCategory } from "@/lib/types";
import { Button } from "@/components/ui";

export interface AssignmentDraft {
  title: string;
  category_id: string | null;
  points_possible: number | null;
  points_earned: number | null;
  due_date: string | null;
  assignment_type: string | null;
  notes: string | null;
  curve_class_mean: number | null;
  curve_class_sd: number | null;
  curve_avg_target: number | null;
  curve_sd_delta: number | null;
}

interface Props {
  open: boolean;
  initial?: GradedAssignment | null;
  categories: GradeCategory[];
  onClose: () => void;
  onSave: (draft: AssignmentDraft) => Promise<void>;
  onDelete?: (() => Promise<void>) | null;
}


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
    curve_class_mean: null,
    curve_class_sd: null,
    curve_avg_target: null,
    curve_sd_delta: null,
  });
  const [saving, setSaving] = React.useState(false);
  const [curveOpen, setCurveOpen] = React.useState(false);
  const [titleTouched, setTitleTouched] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) {
      setTitleTouched(false);
      setDraft({
        title: initial?.title ?? "",
        category_id: initial?.category_id ?? null,
        points_possible: initial?.points_possible ?? null,
        points_earned: initial?.points_earned ?? null,
        due_date: initial?.due_date ?? null,
        assignment_type: initial?.assignment_type ?? null,
        notes: initial?.notes ?? null,
        curve_class_mean: initial?.curve_class_mean ?? null,
        curve_class_sd: initial?.curve_class_sd ?? null,
        curve_avg_target: initial?.curve_avg_target ?? null,
        curve_sd_delta: initial?.curve_sd_delta ?? null,
      });
      setCurveOpen(initial?.curve_class_mean != null);
    }
  }, [open, initial]);

  if (!mounted || !open) return null;

  const dueDateInvalid = !!draft.due_date && (() => {
    const d = new Date(draft.due_date + "T00:00:00");
    return isNaN(d.getTime()) || draft.due_date !== d.toISOString().slice(0, 10);
  })();

  const valid = draft.title.trim() !== "" &&
    (draft.points_possible === null || draft.points_possible > 0) &&
    !dueDateInvalid;

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
          {initial ? "Edit Assignment" : "New Assignment"}
        </h3>
        <div style={{ display: "grid", gap: 10 }}>
          <label>
            Title <span style={{ color: "var(--err)" }}>*</span>
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              onBlur={() => setTitleTouched(true)}
              style={{
                width: "100%", padding: 6, borderRadius: 6,
                border: `1px solid ${titleTouched && !draft.title.trim() ? "var(--err)" : "var(--border)"}`,
              }}
            />
            {titleTouched && !draft.title.trim() && (
              <span style={{ fontSize: 11, color: "var(--err)", marginTop: 3, display: "block" }}>
                Required
              </span>
            )}
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
              <option value="">Uncategorized</option>
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
              Total
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
            Due Date
            <input
              type="date"
              value={draft.due_date ?? ""}
              onChange={(e) => setDraft({ ...draft, due_date: e.target.value || null })}
              style={{
                width: "100%", padding: 6, borderRadius: 6,
                border: `1px solid ${dueDateInvalid ? "var(--err)" : "var(--border)"}`,
              }}
            />
            {dueDateInvalid && (
              <span style={{ fontSize: 11, color: "var(--err)", marginTop: 3, display: "block" }}>
                Invalid date
              </span>
            )}
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
          {/* Bell Curve section */}
          <div>
            <button
              type="button"
              onClick={() => setCurveOpen((v) => !v)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                background: "none",
                border: 0,
                padding: "4px 0",
                cursor: "pointer",
                fontFamily: "var(--font-sans)",
                fontSize: 13,
                color: "var(--accent)",
                fontWeight: 500,
              }}
            >
              <span style={{
                display: "inline-block",
                transition: "transform 0.15s",
                transform: curveOpen ? "rotate(0deg)" : "rotate(-90deg)",
              }}>▾</span>
              Bell Curve
            </button>
            {curveOpen && (
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                <p style={{ margin: 0, fontSize: 11, color: "var(--text-dim)", lineHeight: 1.5 }}>
                  A bell curve adjusts your score based on class performance.
                  Enter the statistics your professor posted after this exam.
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ flex: 1 }}>
                    Class Average (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="e.g. 68"
                      value={draft.curve_class_mean !== null ? (draft.curve_class_mean * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_class_mean: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                  <label style={{ flex: 1 }}>
                    Std Dev (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="e.g. 12"
                      value={draft.curve_class_sd !== null ? (draft.curve_class_sd * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_class_sd: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                </div>
                <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)" }}>
                  Override course curve policy for this assignment only (optional):
                </p>
                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ flex: 1 }}>
                    Avg maps to (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="Course default"
                      value={draft.curve_avg_target !== null ? (draft.curve_avg_target * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_avg_target: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                  <label style={{ flex: 1 }}>
                    Grade per SD (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      placeholder="Course default"
                      value={draft.curve_sd_delta !== null ? (draft.curve_sd_delta * 100).toFixed(1) : ""}
                      onChange={(e) => setDraft({
                        ...draft,
                        curve_sd_delta: e.target.value === "" ? null : Number(e.target.value) / 100,
                      })}
                      style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
                    />
                  </label>
                </div>
                {(draft.curve_class_mean !== null || draft.curve_class_sd !== null) && (
                  <button
                    type="button"
                    onClick={() => setDraft({
                      ...draft,
                      curve_class_mean: null,
                      curve_class_sd: null,
                      curve_avg_target: null,
                      curve_sd_delta: null,
                    })}
                    style={{ fontSize: 11, color: "var(--err)", background: "none", border: 0,
                      padding: 0, cursor: "pointer", textAlign: "left" }}
                  >
                    Remove curve from this assignment
                  </button>
                )}
              </div>
            )}
          </div>
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
            <Button
              variant="primary"
              size="sm"
              disabled={!valid || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(draft); onClose(); }
                finally { setSaving(false); }
              }}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
