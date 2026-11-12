"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importGenerate } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";
import s from "../FlashcardImportModal.module.css";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  documents: LibraryDoc[];
  /** The library is still being read: not yet "no documents". */
  documentsLoading?: boolean;
  onCards: (cards: ParsedCard[]) => void;
}

function documentPlaceholder(loading: boolean, count: number): string {
  if (count) return "Pick a document…";
  return loading ? "Loading your documents…" : "No library documents yet";
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

export function AiTab({ documents, documentsLoading = false, onCards }: Props) {
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
    <div className={s.tab}>
      {mode === "paste" ? (
        <textarea
          className={s.textarea}
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Paste lecture notes, a study guide, or a course topic."
        />
      ) : (
        <div className={s.fill}>
          <CustomSelect
            className={`${s.select} ${s.selectFill}`}
            size="sm"
            value={docId}
            onChange={setDocId}
            placeholder={documentPlaceholder(documentsLoading, documents.length)}
            options={documents.map(d => ({ value: d.id, label: d.file_name, description: d.category }))}
          />
        </div>
      )}

      <div className={s.options}>
        <div className={`${s.seg} ${s.segInline}`} role="group" aria-label="Generate from">
          <button type="button" className={s.segOpt} aria-pressed={mode === "paste"} onClick={() => setMode("paste")}>
            Paste notes
          </button>
          <button type="button" className={s.segOpt} aria-pressed={mode === "library_doc"} onClick={() => setMode("library_doc")}>
            From library
          </button>
        </div>

        <div className={s.optionsLine}>
          <div className={s.pairs}>
            <CustomSelect
              className={`${s.select} ${s.pairSelect} ${s.pairSelectWide}`}
              size="sm"
              ariaLabel="Count"
              value={count}
              onChange={setCount}
              options={COUNT_OPTIONS}
            />
            <CustomSelect
              className={`${s.select} ${s.pairSelect} ${s.pairSelectWide}`}
              size="sm"
              ariaLabel="Difficulty"
              value={difficulty}
              onChange={v => setDifficulty(v as "recall" | "application" | "conceptual")}
              options={DIFFICULTY_OPTIONS}
            />
          </div>
          <button type="button" className={`btn btn--primary ${s.go}`} onClick={generate} disabled={busy || !canGo}>
            {busy ? "Generating…" : "Generate cards"}
          </button>
        </div>
      </div>
    </div>
  );
}
