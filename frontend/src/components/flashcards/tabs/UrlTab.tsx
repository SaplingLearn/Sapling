"use client";
import React from "react";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { ApiError, importParse } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

// 400 = the submitted link is not a quizlet.com set link (the student can fix
// it); 422 = Quizlet itself refused or redirected away (fall back to Paste).
type Problem = { kind: "rejected" | "blocked"; detail: string };

function problemFrom(err: unknown): Problem | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | undefined;
  const detail = typeof body?.detail === "string" ? body.detail : "";
  if (err.status === 400) return { kind: "rejected", detail };
  if (err.status === 422) return { kind: "blocked", detail };
  return null;
}

export function UrlTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<Problem | null>(null);

  const fetchUrl = async () => {
    if (!userId || !url.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      const res = await importParse(userId, "url", url.trim());
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Found ${res.cards.length} cards.`);
    } catch (err) {
      const p = problemFrom(err);
      if (p) {
        setProblem(p);
      } else {
        toast.error(`Fetch failed: ${String(err)}`);
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
      {problem?.kind === "rejected" && (
        <div role="alert" className="card" style={{ padding: 14, fontSize: 13, color: "var(--text-dim)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            That isn&apos;t a Quizlet set link
          </div>
          Only links to a public set on quizlet.com can be fetched, like{" "}
          <code>https://quizlet.com/123456789/set-name</code>. Copy the link from
          the set&apos;s page in your browser, or use the <strong>Paste</strong> tab
          for cards from anywhere else.
        </div>
      )}
      {problem?.kind === "blocked" && (
        <div role="alert" className="card" style={{ padding: 14, fontSize: 13, color: "var(--text-dim)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            Couldn&apos;t fetch this URL
          </div>
          Quizlet may be blocking automated requests. Try the <strong>Paste</strong> tab
          instead — open the set in your browser, click <em>Export</em> in the
          three-dot menu, then paste the export text.
          {problem.detail && (
            <div style={{ marginTop: 6, fontSize: 12 }}>{problem.detail}</div>
          )}
        </div>
      )}
    </div>
  );
}
