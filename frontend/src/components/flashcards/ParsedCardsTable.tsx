"use client";
import React from "react";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCleanup, type ImportCard } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props {
  cards: ParsedCard[];
  onChange: (next: ParsedCard[]) => void;
  reverseEnabled: boolean;
  onReverseToggle: (next: boolean) => void;
}

export function ParsedCardsTable({ cards, onChange, reverseEnabled, onReverseToggle }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [cleaning, setCleaning] = React.useState(false);

  const validCount = cards.filter(c => !c.error && c.front && c.back).length;

  const updateRow = (idx: number, patch: Partial<ParsedCard>) => {
    const next = [...cards];
    const merged = { ...next[idx], ...patch };
    if (merged.front && merged.back) merged.error = undefined;
    next[idx] = merged;
    onChange(next);
  };

  const removeRow = (idx: number) => onChange(cards.filter((_, i) => i !== idx));

  const cleanup = async () => {
    if (!userId) return;
    const valid: ImportCard[] = cards.filter(c => c.front && c.back).map(c => ({ front: c.front, back: c.back }));
    if (valid.length === 0) { toast.warn("No valid cards to clean up."); return; }
    setCleaning(true);
    try {
      const res = await importCleanup(userId, valid);
      onChange(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success("Cleaned up.");
    } catch (err) {
      toast.error(`Cleanup failed: ${String(err)}`);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="label-micro">{validCount} valid · {cards.length - validCount} flagged</span>
        <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={reverseEnabled} onChange={e => onReverseToggle(e.target.checked)} />
          Generate reverse cards
        </label>
        <button className="btn btn--sm" onClick={cleanup} disabled={cleaning || cards.length === 0}>
          <Icon name="sparkle" size={11} /> {cleaning ? "Cleaning…" : "Clean up with AI"}
        </button>
      </div>

      <div style={{
        maxHeight: 360, overflowY: "auto", border: "1px solid var(--border)",
        borderRadius: "var(--r-md)", background: "var(--bg-panel)",
      }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead style={{ position: "sticky", top: 0, background: "var(--bg-subtle)" }}>
            <tr>
              <th style={{ padding: "6px 8px", textAlign: "left", width: 36 }}>#</th>
              <th style={{ padding: "6px 8px", textAlign: "left" }}>Term</th>
              <th style={{ padding: "6px 8px", textAlign: "left" }}>Definition</th>
              <th style={{ width: 32 }} />
            </tr>
          </thead>
          <tbody>
            {cards.map((c, i) => (
              <tr key={i} style={{
                borderTop: "1px solid var(--border)",
                borderLeft: c.error ? "3px solid var(--err)" : "3px solid transparent",
              }} title={c.error}>
                <td style={{ padding: "4px 8px", color: "var(--text-muted)" }}>{c.row}</td>
                <td style={{ padding: "4px 8px" }}>
                  <input
                    value={c.front}
                    onChange={e => updateRow(i, { front: e.target.value })}
                    style={{ width: "100%", background: "transparent", border: "none", outline: "none", color: "var(--text)" }}
                  />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input
                    value={c.back}
                    onChange={e => updateRow(i, { back: e.target.value })}
                    style={{ width: "100%", background: "transparent", border: "none", outline: "none", color: "var(--text)" }}
                  />
                </td>
                <td>
                  <button onClick={() => removeRow(i)} className="btn btn--sm btn--ghost" style={{ color: "var(--err)" }} title="Delete row">
                    <Icon name="x" size={11} />
                  </button>
                </td>
              </tr>
            ))}
            {cards.length === 0 && (
              <tr><td colSpan={4} style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
                No cards parsed yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
