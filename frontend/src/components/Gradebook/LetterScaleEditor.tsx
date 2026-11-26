"use client";
import React from "react";
import type { LetterScaleTier } from "@/lib/types";
import { Button } from "@/components/ui";
import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";

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
  const toast = useToast();
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
      <p className="text-sm text-text-dim mt-0 mx-0 mb-3">
        Edit the floor percentage for each letter. Tiers must stay in descending order.
      </p>
      <ul className="list-none m-0 p-0">
        {tiers.map((t, i) => (
          <li key={i} className="flex gap-2 mb-1.5">
            <input
              value={t.letter}
              onChange={(e) =>
                setTiers((arr) =>
                  arr.map((x, idx) => (idx === i ? { ...x, letter: e.target.value } : x)),
                )
              }
              className="w-12 p-1 border border-border rounded-xs"
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
              className="w-17.5 p-1 border border-border rounded-xs"
            />
            <span className="self-center text-text-dim">%+</span>
          </li>
        ))}
      </ul>
      <div
        className="mt-3 flex flex-wrap gap-2 justify-between items-center"
      >
        <button
          type="button"
          disabled={saving}
          // Deliberately no onClose: on success the modal stays open showing
          // the restored default scale, as before.
          onClick={async () => {
            setSaving(true);
            try { await onSave(null); }
            catch (err) { toast.error(humanizeError(err, "Couldn't reset the letter scale. Try again.")); }
            finally { setSaving(false); }
          }}
        >
          Reset to default
        </button>
        <div className="flex gap-2">
          <button type="button" onClick={onClose}>Cancel</button>
          <Button
            variant="primary"
            size="sm"
            disabled={!monotonic || saving}
            // On failure the modal stays open (no onClose) so the user can
            // see the toast and retry — closing would look like success.
            onClick={async () => {
              setSaving(true);
              try { await onSave(tiers); onClose(); }
              catch (err) { toast.error(humanizeError(err, "Couldn't save the letter scale. Try again.")); }
              finally { setSaving(false); }
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
      {!monotonic && (
        <p className="text-err text-sm mt-1.5">
          Tiers must be sorted descending by minimum.
        </p>
      )}
    </Dialog>
  );
}
