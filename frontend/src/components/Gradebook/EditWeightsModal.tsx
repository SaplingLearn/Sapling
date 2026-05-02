"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { GradeCategory } from "@/lib/types";

interface Draft {
  id?: string;
  name: string;
  weight: number;
  sort_order: number;
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
          id: c.id, name: c.name, weight: c.weight, sort_order: c.sort_order,
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
    setDrafts((arr) => [...arr, { name: "", weight: 0, sort_order: arr.length }]);

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
          minWidth: 420, maxWidth: 560, maxHeight: "80vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>Edit categories &amp; weights</h3>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {drafts.map((d, i) => (
            <li key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input
                value={d.name}
                placeholder="Category name"
                onChange={(e) => update(i, { name: e.target.value })}
                style={{ flex: 1, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
              <input
                type="number"
                value={d.weight}
                min={0}
                max={100}
                onChange={(e) => update(i, { weight: Number(e.target.value) })}
                style={{ width: 70, padding: 6, border: "1px solid var(--border)", borderRadius: 6 }}
              />
              <span style={{ alignSelf: "center" }}>%</span>
              <button type="button" onClick={() => remove(i)} aria-label="Remove">
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
