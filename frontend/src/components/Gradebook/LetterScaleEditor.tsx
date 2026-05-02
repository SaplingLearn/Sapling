"use client";
import React from "react";
import { createPortal } from "react-dom";
import type { LetterScaleTier } from "@/lib/types";

const DEFAULT_SCALE: LetterScaleTier[] = [
  { min: 93, letter: "A" }, { min: 90, letter: "A-" },
  { min: 87, letter: "B+" }, { min: 83, letter: "B" }, { min: 80, letter: "B-" },
  { min: 77, letter: "C+" }, { min: 73, letter: "C" }, { min: 70, letter: "C-" },
  { min: 67, letter: "D+" }, { min: 63, letter: "D" }, { min: 60, letter: "D-" },
  { min: 0, letter: "F" },
];

interface Props {
  open: boolean;
  initial: LetterScaleTier[] | null;
  onClose: () => void;
  onSave: (scale: LetterScaleTier[] | null) => Promise<void>;
}

export function LetterScaleEditor({ open, initial, onClose, onSave }: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [tiers, setTiers] = React.useState<LetterScaleTier[]>(DEFAULT_SCALE);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    if (open) setTiers(initial ?? DEFAULT_SCALE);
  }, [open, initial]);

  if (!mounted || !open) return null;

  const monotonic = tiers.every(
    (t, i) => i === 0 || t.min <= tiers[i - 1].min,
  );

  return createPortal(
    <div
      role="dialog" aria-modal="true"
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
          minWidth: 360, maxHeight: "80vh", overflow: "auto",
        }}
      >
        <h3 style={{ margin: "0 0 12px" }}>Letter scale</h3>
        <p style={{ fontSize: 12, color: "var(--text-dim)", margin: "0 0 12px" }}>
          Edit the floor percentage for each letter. Tiers must stay in descending order.
        </p>
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {tiers.map((t, i) => (
            <li key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              <input
                value={t.letter}
                onChange={(e) =>
                  setTiers((arr) =>
                    arr.map((x, idx) => (idx === i ? { ...x, letter: e.target.value } : x)),
                  )
                }
                style={{ width: 48, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
              />
              <input
                type="number"
                value={t.min}
                onChange={(e) =>
                  setTiers((arr) =>
                    arr.map((x, idx) =>
                      idx === i ? { ...x, min: Number(e.target.value) } : x,
                    ),
                  )
                }
                style={{ width: 70, padding: 4, border: "1px solid var(--border)", borderRadius: 4 }}
              />
              <span style={{ alignSelf: "center", color: "var(--text-dim)" }}>%+</span>
            </li>
          ))}
        </ul>
        <div
          style={{
            marginTop: 12, display: "flex",
            justifyContent: "space-between", alignItems: "center",
          }}
        >
          <button type="button" onClick={() => onSave(null)} disabled={saving}>
            Reset to default
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              disabled={!monotonic || saving}
              onClick={async () => {
                setSaving(true);
                try { await onSave(tiers); onClose(); }
                finally { setSaving(false); }
              }}
              style={{
                background: monotonic ? "var(--accent)" : "var(--bg-soft)",
                color: monotonic ? "#fff" : "var(--text-dim)",
                border: 0, borderRadius: 6, padding: "6px 14px",
                cursor: monotonic ? "pointer" : "not-allowed",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
        {!monotonic && (
          <p style={{ color: "var(--err)", fontSize: 12, marginTop: 6 }}>
            Tiers must be sorted descending by minimum.
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
}
