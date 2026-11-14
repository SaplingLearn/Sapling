"use client";
import React from "react";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import { parseCSV, parseTSV, parseJSON, type ParsedCard } from "@/lib/flashcardParsers";
import s from "../FlashcardImportModal.module.css";

interface Props { onCards: (cards: ParsedCard[]) => void }

const MAX_BYTES = 5 * 1024 * 1024;

async function readAsText(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result ?? ""));
    r.onerror = () => rej(r.error);
    r.readAsText(file);
  });
}

async function readAsBase64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => {
      const dataUrl = String(r.result ?? "");
      res(dataUrl.split(",", 2)[1] ?? "");
    };
    r.onerror = () => rej(r.error);
    r.readAsDataURL(file);
  });
}

export function UploadTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!userId) return;
    if (file.size > MAX_BYTES) { toast.error("File exceeds 5MB. Try splitting it."); return; }
    setBusy(true);
    try {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (ext === "csv") onCards(parseCSV(await readAsText(file)));
      else if (ext === "tsv") onCards(parseTSV(await readAsText(file)));
      else if (ext === "txt") onCards(parseTSV(await readAsText(file))); // tab/newline default
      else if (ext === "json") onCards(parseJSON(await readAsText(file)));
      else if (ext === "xlsx") {
        const res = await importParse(userId, "xlsx", await readAsBase64(file));
        onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      } else if (ext === "apkg") {
        const res = await importParse(userId, "anki", await readAsBase64(file));
        onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      } else {
        toast.error(`Unsupported file type: .${ext}`);
      }
    } catch (err) {
      toast.error(`Couldn't parse: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={s.tab}>
      <button
        type="button"
        className={s.drop}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); }}
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
      >
        <Icon name="upload" size={20} />
        <span className={s.dropText}>
          {busy ? "Parsing…" : "Drop or click to upload .csv, .tsv, .txt, .json, .xlsx, .apkg"}
        </span>
        <span className={s.dropMeta}>Max 5MB</span>
      </button>
      {/* Opened by the button above, which is what the keyboard reaches. */}
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.txt,.json,.xlsx,.apkg"
        hidden
        tabIndex={-1}
        aria-label="File to import"
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }}
      />
    </div>
  );
}
