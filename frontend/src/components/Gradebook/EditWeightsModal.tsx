"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradeCategory } from "@/lib/types";

interface Draft {
  id?: string;
  name: string;
  weight: number;
  sort_order: number;
  drop_lowest: number;
}

interface Props {
  open: boolean;
  initial: GradeCategory[];
  onClose: () => void;
  onSave: (categories: Draft[]) => Promise<void>;
}

export function EditWeightsModal({ open, initial, onClose, onSave }: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [drafts, setDrafts] = React.useState<Draft[]>([]);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) {
      setDrafts(
        initial.map((c) => ({
          id: c.id,
          name: c.name,
          weight: c.weight,
          sort_order: c.sort_order,
          drop_lowest: c.drop_lowest ?? 0,
        })),
      );
    }
  }, [open, initial]);

  if (!mounted || !open) return null;

  const total = drafts.reduce((s, d) => s + Number(d.weight || 0), 0);
  const valid = Math.abs(total - 100) <= 0.5 && drafts.every((d) => d.name.trim() !== "");

  const update = (i: number, patch: Partial<Draft>) =>
    setDrafts((arr) => arr.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  const remove = (i: number) =>
    setDrafts((arr) => arr.filter((_, idx) => idx !== i));
  const add = () =>
    setDrafts((arr) => [
      ...arr,
      { name: "", weight: 0, sort_order: arr.length, drop_lowest: 0 },
    ]);

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
          minWidth: 520, maxWidth: 640, maxHeight: "80vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 4px" }}>Edit categories &amp; weights</h3>
        <p
          style={{
            margin: "0 0 16px",
            fontSize: 12,
            color: "var(--text-dim)",
            lineHeight: 1.5,
          }}
        >
          Weights must sum to 100%. Set <strong>Drop</strong> to the number of
          lowest-scoring graded assignments to exclude from that category&apos;s
          average — e.g. &quot;drop 2 lowest homeworks.&quot;
        </p>
        <div
          className="mono"
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 80px 80px 28px",
            gap: 6,
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            padding: "0 2px 6px",
          }}
        >
          <span>Name</span>
          <span style={{ textAlign: "right" }}>Weight</span>
          <span style={{ textAlign: "right" }}>Drop</span>
          <span />
        </div>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {drafts.map((d, i) => (
            <li
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) 80px 80px 28px",
                gap: 6,
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <input
                value={d.name}
                placeholder="Category name"
                onChange={(e) => update(i, { name: e.target.value })}
                style={{ padding: 6, border: "1px solid var(--border)", borderRadius: 6, minWidth: 0 }}
              />
              <div style={{ position: "relative" }}>
                <input
                  type="number"
                  value={d.weight}
                  min={0}
                  max={100}
                  onChange={(e) => update(i, { weight: Number(e.target.value) })}
                  style={{
                    width: "100%",
                    padding: "6px 22px 6px 6px",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    textAlign: "right",
                  }}
                />
                <span
                  style={{
                    position: "absolute",
                    right: 8,
                    top: "50%",
                    transform: "translateY(-50%)",
                    fontSize: 11,
                    color: "var(--text-muted)",
                    pointerEvents: "none",
                  }}
                >
                  %
                </span>
              </div>
              <input
                type="number"
                value={d.drop_lowest}
                min={0}
                max={50}
                step={1}
                title="Number of lowest-scoring graded assignments to drop from this category"
                onChange={(e) =>
                  update(i, { drop_lowest: Math.max(0, Math.floor(Number(e.target.value) || 0)) })
                }
                style={{
                  width: "100%",
                  padding: "6px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  textAlign: "right",
                }}
              />
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label="Remove category"
                title="Remove"
                style={{
                  background: "transparent",
                  border: 0,
                  color: "var(--text-muted)",
                  cursor: "pointer",
                  fontSize: 16,
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
        <button type="button" onClick={add} style={{ fontSize: 13, marginTop: 4 }}>
          + Add category
        </button>
        <div
          style={{
            marginTop: 16, padding: "8px 0",
            borderTop: "1px solid var(--border)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}
        >
          <span style={{ color: valid ? "var(--accent)" : "var(--err)" }}>
            Total: {total.toFixed(1)}% {valid ? "✓" : `(need 100%)`}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!valid || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(drafts); onClose(); }
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
