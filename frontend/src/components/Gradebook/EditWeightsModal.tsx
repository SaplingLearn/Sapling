"use client";
import React from "react";
import type { GradeCategory } from "@/lib/types";
import { Button } from "@/components/ui";
import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import { cn } from "@/lib/cn";

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
  const toast = useToast();
  const [drafts, setDrafts] = React.useState<Draft[]>([]);
  const [saving, setSaving] = React.useState(false);
  const dragIndex = React.useRef<number | null>(null);
  const [dragOver, setDragOver] = React.useState<number | null>(null);

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

  const handleDragStart = (i: number) => {
    dragIndex.current = i;
  };
  const handleDragOver = (e: React.DragEvent, i: number) => {
    e.preventDefault();
    if (dragIndex.current !== null && dragIndex.current !== i) setDragOver(i);
  };
  const handleDrop = (i: number) => {
    const from = dragIndex.current;
    if (from === null || from === i) return;
    setDrafts((arr) => {
      const next = [...arr];
      const [item] = next.splice(from, 1);
      next.splice(i, 0, item);
      return next.map((d, idx) => ({ ...d, sort_order: idx }));
    });
    dragIndex.current = null;
    setDragOver(null);
  };
  const handleDragEnd = () => {
    dragIndex.current = null;
    setDragOver(null);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Edit categories & weights"
      size="lg"
      padding="20px"
    >
      <p
        className="mt-0 mx-0 mb-4 text-sm text-text-dim leading-[1.5]"
      >
        Weights must sum to 100%. Set <strong>Drop</strong> to the number of
        lowest-scoring graded assignments to exclude from that category&apos;s
        average (e.g. &quot;drop 2 lowest homeworks&quot;). Drag the handle to reorder.
      </p>
      <div
        className="mono grid grid-cols-[24px_minmax(0,_1fr)_80px_80px_28px] gap-1.5 text-sm text-text-muted pt-0 px-0.5 pb-1.5"
      >
        <span />
        <span>Name</span>
        <span className="text-right">Weight</span>
        <span className="text-right">Drop</span>
        <span />
      </div>
      <ul className="list-none m-0 p-0">
        {drafts.map((d, i) => (
          <li
            key={d.id ?? i}
            draggable
            onDragStart={() => handleDragStart(i)}
            onDragOver={(e) => handleDragOver(e, i)}
            onDrop={() => handleDrop(i)}
            onDragEnd={handleDragEnd}
            className={cn("grid grid-cols-[24px_minmax(0,_1fr)_80px_80px_28px] gap-1.5 items-center mb-2 rounded-sm [outline-offset:2px] [transition:opacity_0.15s]", dragOver === i ? "[outline:2px_solid_var(--accent)]" : "outline-none", dragIndex.current === i ? "opacity-40" : "opacity-100")}
          >
            <span
              title="Drag to reorder"
              className="cursor-grab text-text-muted text-lg leading-none select-none flex items-center justify-center"
            >
              ⠿
            </span>
            <input
              value={d.name}
              placeholder="Category name"
              onChange={(e) => update(i, { name: e.target.value })}
              className="p-1.5 border border-border rounded-sm min-w-0"
            />
            <div className="relative">
              <input
                type="number"
                value={d.weight}
                min={0}
                max={100}
                onChange={(e) => update(i, { weight: Number(e.target.value) })}
                className="w-full pt-1.5 pr-5.5 pb-1.5 pl-1.5 border border-border rounded-sm text-right"
              />
              <span
                className="absolute right-2 top-1/2 [transform:translateY(-50%)] text-xs text-text-muted pointer-events-none"
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
              className="w-full p-1.5 border border-border rounded-sm text-right"
            />
            <button
              type="button"
              onClick={() => remove(i)}
              aria-label="Remove category"
              title="Remove"
              className="bg-transparent border-0 text-text-muted cursor-pointer text-lg leading-none"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <button type="button" onClick={add} className="text-md mt-1">
        + Add category
      </button>
      <div
        className="mt-4 py-2 px-0 border-t border-t-border flex flex-wrap gap-2 justify-between items-center"
      >
        <span className={cn(valid ? "text-accent" : "text-err")}>
          Total: {total.toFixed(1)}% {valid ? "✓" : `(need 100%)`}
        </span>
        <div className="flex gap-2">
          <button type="button" onClick={onClose}>Cancel</button>
          <Button
            variant="primary"
            size="sm"
            disabled={!valid || saving}
            // On failure the modal stays open (no onClose) so the user can
            // see the toast and retry — closing would look like success.
            onClick={async () => {
              setSaving(true);
              try { await onSave(drafts); onClose(); }
              catch (err) { toast.error(humanizeError(err, "Couldn't save categories. Try again.")); }
              finally { setSaving(false); }
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
