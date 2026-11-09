"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importGenerate } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  documents: LibraryDoc[];
  onCards: (cards: ParsedCard[]) => void;
}

const COUNT_OPTIONS = [
  { value: "10", label: "10 cards" },
  { value: "25", label: "25 cards" },
  { value: "50", label: "50 cards" },
  { value: "auto", label: "Auto" },
];

const DIFFICULTY_OPTIONS = [
  { value: "recall", label: "Recall" },
  { value: "application", label: "Application" },
  { value: "conceptual", label: "Conceptual" },
];

export function AiTab({ documents, onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [mode, setMode] = React.useState<"paste" | "library_doc">("paste");
  const [text, setText] = React.useState("");
  const [docId, setDocId] = React.useState("");
  const [count, setCount] = React.useState<string>("25");
  const [difficulty, setDifficulty] = React.useState<"recall" | "application" | "conceptual">("recall");
  const [busy, setBusy] = React.useState(false);

  const numericCount = count === "auto" ? 25 : parseInt(count, 10);

  const generate = async () => {
    if (!userId) return;
    setBusy(true);
    try {
      const res = mode === "paste"
        ? await importGenerate(userId, { source: "paste", text, count: numericCount, difficulty })
        : await importGenerate(userId, { source: "library_doc", documentId: docId, count: numericCount, difficulty });
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Generated ${res.cards.length} cards.`);
    } catch (err) {
      toast.error(`Generate failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const canGo = mode === "paste" ? text.trim().length > 0 : !!docId;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn--sm" style={{ fontWeight: mode === "paste" ? 600 : 400 }} onClick={() => setMode("paste")}>Paste notes</button>
        <button className="btn btn--sm" style={{ fontWeight: mode === "library_doc" ? 600 : 400 }} onClick={() => setMode("library_doc")}>From library</button>
      </div>

      {mode === "paste" ? (
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Paste lecture notes, a study guide, or a course topic."
          style={{ minHeight: 160, padding: 12, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)", resize: "vertical" }}
        />
      ) : (
        <CustomSelect
          value={docId}
          onChange={setDocId}
          placeholder={documents.length ? "Pick a document…" : "No library documents yet"}
          options={documents.map(d => ({ value: d.id, label: d.file_name, description: d.category }))}
        />
      )}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 140 }}>
          <div className="label-micro">Count</div>
          <CustomSelect value={count} onChange={setCount} options={COUNT_OPTIONS} />
        </div>
        <div style={{ minWidth: 180 }}>
          <div className="label-micro">Difficulty</div>
          <CustomSelect
            value={difficulty}
            onChange={v => setDifficulty(v as "recall" | "application" | "conceptual")}
            options={DIFFICULTY_OPTIONS}
          />
        </div>
      </div>

      <button className="btn btn--primary btn--sm" onClick={generate} disabled={busy || !canGo}>
        {busy ? "Generating…" : "Generate cards"}
      </button>
    </div>
  );
}
