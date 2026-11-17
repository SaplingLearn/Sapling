"use client";
import React from "react";
import type { GradedAssignment, GradeCategory } from "@/lib/types";
import { Button } from "@/components/ui";
import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import {
  CLEARED_CURVE,
  draftFromAssignment,
  emptyDraft,
  formatPercent,
  hasCurveStats,
  isDraftValid,
  isDueDateInvalid,
  parsePercent,
  parsePoints,
} from "./assignmentDraft";

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


type Patch = (fields: Partial<AssignmentDraft>) => void;
type Toast = ReturnType<typeof useToast>;

/** Draft + UI state, re-seeded from `initial` every time the modal opens. */
function useAssignmentForm(open: boolean, initial: GradedAssignment | null | undefined) {
  const [draft, setDraft] = React.useState<AssignmentDraft>(emptyDraft);
  const [saving, setSaving] = React.useState(false);
  const [curveOpen, setCurveOpen] = React.useState(false);
  const [titleTouched, setTitleTouched] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setTitleTouched(false);
      setDraft(draftFromAssignment(initial));
      setCurveOpen(initial?.curve_class_mean != null);
    }
  }, [open, initial]);

  // Spreads the draft of this render, exactly like the inline setDraft calls did.
  const patch: Patch = (fields) => setDraft({ ...draft, ...fields });

  return { draft, patch, saving, setSaving, curveOpen, setCurveOpen, titleTouched, setTitleTouched };
}

/**
 * Runs a save/delete: busy while pending, closes on success. On failure the
 * modal stays open (no onClose) so the user can see the toast and retry —
 * closing would look like success.
 */
async function runAndClose(
  action: () => Promise<void>,
  onClose: () => void,
  setSaving: (saving: boolean) => void,
  toast: Toast,
  fallback: string,
) {
  setSaving(true);
  try { await action(); onClose(); }
  catch (err) { toast.error(humanizeError(err, fallback)); }
  finally { setSaving(false); }
}

function TitleField({ titleRef, title, touched, patch, onBlur }: {
  titleRef: React.RefObject<HTMLInputElement | null>;
  title: string;
  touched: boolean;
  patch: Patch;
  onBlur: () => void;
}) {
  const missing = touched && !title.trim();
  return (
    <label>
      Title <span style={{ color: "var(--err)" }}>*</span>
      <input
        ref={titleRef}
        data-testid="gradebook-assignment-title"
        value={title}
        onChange={(e) => patch({ title: e.target.value })}
        onBlur={onBlur}
        style={{
          width: "100%", padding: 6, borderRadius: 6,
          border: `1px solid ${missing ? "var(--err)" : "var(--border)"}`,
        }}
      />
      {missing && (
        <span style={{ fontSize: 11, color: "var(--err)", marginTop: 3, display: "block" }}>
          Required
        </span>
      )}
    </label>
  );
}

function DueDateField({ dueDate, invalid, patch }: {
  dueDate: string | null;
  invalid: boolean;
  patch: Patch;
}) {
  return (
    <label>
      Due Date
      <input
        type="date"
        value={dueDate ?? ""}
        onChange={(e) => patch({ due_date: e.target.value || null })}
        style={{
          width: "100%", padding: 6, borderRadius: 6,
          border: `1px solid ${invalid ? "var(--err)" : "var(--border)"}`,
        }}
      />
      {invalid && (
        <span style={{ fontSize: 11, color: "var(--err)", marginTop: 3, display: "block" }}>
          Invalid date
        </span>
      )}
    </label>
  );
}

function CurveSection({ draft, patch, curveOpen, onToggle }: {
  draft: AssignmentDraft;
  patch: Patch;
  curveOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
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
                value={formatPercent(draft.curve_class_mean)}
                onChange={(e) => patch({ curve_class_mean: parsePercent(e.target.value) })}
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
                value={formatPercent(draft.curve_class_sd)}
                onChange={(e) => patch({ curve_class_sd: parsePercent(e.target.value) })}
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
                value={formatPercent(draft.curve_avg_target)}
                onChange={(e) => patch({ curve_avg_target: parsePercent(e.target.value) })}
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
                value={formatPercent(draft.curve_sd_delta)}
                onChange={(e) => patch({ curve_sd_delta: parsePercent(e.target.value) })}
                style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
            </label>
          </div>
          {hasCurveStats(draft) && (
            <button
              type="button"
              onClick={() => patch(CLEARED_CURVE)}
              style={{ fontSize: 11, color: "var(--err)", background: "none", border: 0,
                padding: 0, cursor: "pointer", textAlign: "left" }}
            >
              Remove curve from this assignment
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ModalFooter({ showDelete, saving, canSave, onDelete, onCancel, onSave }: {
  showDelete: boolean;
  saving: boolean;
  canSave: boolean;
  onDelete: () => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div
      style={{
        marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)",
        display: "flex", flexWrap: "wrap", gap: 8,
        justifyContent: "space-between", alignItems: "center",
      }}
    >
      <div>
        {showDelete && (
          <button
            type="button"
            disabled={saving}
            onClick={onDelete}
            style={{ color: "var(--err)" }}
          >
            Delete
          </button>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" onClick={onCancel}>Cancel</button>
        <Button
          variant="primary"
          size="sm"
          data-testid="gradebook-assignment-save"
          disabled={!canSave || saving}
          onClick={onSave}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}

export function AssignmentModal({
  open, initial, categories, onClose, onSave, onDelete,
}: Props) {
  const toast = useToast();
  const titleRef = React.useRef<HTMLInputElement>(null);
  const {
    draft, patch, saving, setSaving, curveOpen, setCurveOpen, titleTouched, setTitleTouched,
  } = useAssignmentForm(open, initial);

  const dueDateInvalid = isDueDateInvalid(draft.due_date);
  const valid = isDraftValid(draft, dueDateInvalid);

  const handleDelete = () => runAndClose(
    () => onDelete!(), onClose, setSaving, toast, "Couldn't delete the assignment. Try again.",
  );
  const handleSave = () => runAndClose(
    () => onSave(draft), onClose, setSaving, toast, "Couldn't save the assignment. Try again.",
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={initial ? "Edit Assignment" : "New Assignment"}
      size="md"
      padding="20px"
      initialFocusRef={titleRef}
    >
      <div style={{ display: "grid", gap: 10 }}>
        <TitleField
          titleRef={titleRef}
          title={draft.title}
          touched={titleTouched}
          patch={patch}
          onBlur={() => setTitleTouched(true)}
        />
        <label>
          Category
          <select
            value={draft.category_id ?? ""}
            onChange={(e) => patch({ category_id: e.target.value || null })}
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
              onChange={(e) => patch({ points_earned: parsePoints(e.target.value) })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
          <label style={{ flex: 1 }}>
            Total
            <input
              type="number"
              value={draft.points_possible ?? ""}
              onChange={(e) => patch({ points_possible: parsePoints(e.target.value) })}
              style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
            />
          </label>
        </div>
        <DueDateField dueDate={draft.due_date} invalid={dueDateInvalid} patch={patch} />
        <label>
          Notes
          <textarea
            value={draft.notes ?? ""}
            onChange={(e) => patch({ notes: e.target.value || null })}
            rows={2}
            style={{ width: "100%", padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
          />
        </label>
        {/* Bell Curve section */}
        <CurveSection
          draft={draft}
          patch={patch}
          curveOpen={curveOpen}
          onToggle={() => setCurveOpen((v) => !v)}
        />
      </div>
      <ModalFooter
        showDelete={!!(onDelete && initial)}
        saving={saving}
        canSave={valid}
        onDelete={handleDelete}
        onCancel={onClose}
        onSave={handleSave}
      />
    </Dialog>
  );
}
