"use client";
import React from "react";
import type { LetterScaleTier } from "@/lib/types";
import { Button } from "@/components/ui";
import Dialog from "@/components/Dialog";

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
  const [tiers, setTiers] = React.useState<LetterScaleTier[]>(DEFAULT_SCALE);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (open) setTiers(initial ?? DEFAULT_SCALE);
  }, [open, initial]);

  const monotonic = tiers.every(
    (t, i) => i === 0 || t.min <= tiers[i - 1].min,
  );

  return (
    <Dialog open={open} onClose={onClose} title="Letter scale" size="sm" padding="20px">
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
          marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8,
          justifyContent: "space-between", alignItems: "center",
        }}
      >
        <button type="button" onClick={() => onSave(null)} disabled={saving}>
          Reset to default
        </button>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <Button
            variant="primary"
            size="sm"
            disabled={!monotonic || saving}
            onClick={async () => {
              setSaving(true);
              try { await onSave(tiers); onClose(); }
              finally { setSaving(false); }
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
      {!monotonic && (
        <p style={{ color: "var(--err)", fontSize: 12, marginTop: 6 }}>
          Tiers must be sorted descending by minimum.
        </p>
      )}
    </Dialog>
  );
}
