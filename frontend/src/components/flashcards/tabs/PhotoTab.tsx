"use client";
import React from "react";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

const MAX_BYTES = 5 * 1024 * 1024;

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

export function PhotoTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!userId) return;
    if (file.size > MAX_BYTES) { toast.error("Image exceeds 5MB."); return; }
    setBusy(true);
    try {
      const res = await importParse(userId, "ocr", await readAsBase64(file), { filename: file.name });
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Extracted ${res.cards.length} cards from image.`);
    } catch (err) {
      toast.error(`OCR failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
      onClick={() => inputRef.current?.click()}
      style={{
        border: "2px dashed var(--border)", borderRadius: "var(--r-md)",
        padding: 32, textAlign: "center", color: "var(--text-muted)", cursor: "pointer",
      }}
    >
      <Icon name="doc" size={20} />
      <div style={{ marginTop: 8, fontSize: 13 }}>
        {busy ? "Reading image…" : "Drop or click to upload a photo of notes (.png, .jpg, .pdf)"}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*,.pdf"
        style={{ display: "none" }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }}
      />
    </div>
  );
}
