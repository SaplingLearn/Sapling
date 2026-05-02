"use client";
import React from "react";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

export function UrlTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [blocked, setBlocked] = React.useState<string | null>(null);

  const fetchUrl = async () => {
    if (!userId || !url.trim()) return;
    setBusy(true);
    setBlocked(null);
    try {
      const res = await importParse(userId, "url", url.trim());
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Found ${res.cards.length} cards.`);
    } catch (err) {
      const msg = String(err);
      if (msg.toLowerCase().includes("blocked") || msg.includes("422")) {
        setBlocked(msg);
      } else {
        toast.error(`Fetch failed: ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
        Paste a public Quizlet set URL.
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://quizlet.com/12345/some-set"
          style={{ flex: 1, padding: 10, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)" }}
        />
        <button className="btn btn--sm btn--primary" onClick={fetchUrl} disabled={busy || !url.trim()}>
          {busy ? "Fetching…" : "Fetch cards"}
        </button>
      </div>
      {blocked && (
        <div className="card" style={{ padding: 14, fontSize: 13, color: "var(--text-dim)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            Couldn&apos;t fetch this URL
          </div>
          Quizlet may be blocking automated requests. Try the <strong>Paste</strong> tab
          instead — open the set in your browser, click <em>Export</em> in the
          three-dot menu, then paste the export text.
        </div>
      )}
    </div>
  );
}
