"use client";
import React from "react";
import dynamic from "next/dynamic";
import { createPortal } from "react-dom";
import type { Document as Doc } from "@/lib/types";
import { useScrollLock } from "@/lib/useScrollLock";
import { Icon } from "../Icon";
import { addedLabel, displayTitle, fileFormat, typeOf } from "./model";

// Lazy-load to keep mermaid/katex/highlight.js out of the server bundle
// (see ChatPanel.tsx).
const MarkdownChat = dynamic(
  () => import("../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

/**
 * "Open": the full reading view of what Sapling extracted from a document
 * (summary + every concept note with its description). The original file is
 * not stored, so this is the document's content as Sapling holds it.
 */
export function LibraryReader({ doc, courseLabel, onClose }: { doc: Doc; courseLabel: string; onClose: () => void }) {
  useScrollLock(true);
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!mounted) return null;
  const notes = doc.concept_notes || [];
  return createPortal(
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(25,37,11,0.45)", zIndex: 200, display: "grid", placeItems: "center", padding: 20 }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={displayTitle(doc.file_name)}
        data-testid="library-reader"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(820px, 100%)", maxHeight: "88vh", overflowY: "auto", background: "#FDFCF9", borderRadius: 16,
          boxShadow: "0 24px 60px rgba(25,37,11,0.24)", padding: "28px 32px 32px", boxSizing: "border-box", color: "#1A1814",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ margin: 0, fontFamily: "var(--font-serif)", fontSize: 28, fontWeight: 600, color: "#2F4417" }}>{displayTitle(doc.file_name)}</h2>
            <div style={{ marginTop: 6, fontSize: 14, color: "#6F6857" }}>
              {[courseLabel, typeOf(doc.category).label, fileFormat(doc.file_name), `Added ${addedLabel(doc.created_at)}`].join(" · ")}
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" data-testid="library-reader-close"
            style={{ width: 36, height: 36, display: "grid", placeItems: "center", border: 0, borderRadius: 9, background: "#F4F1EA", color: "#3F3B31", cursor: "pointer" }}>
            <Icon name="x" size={12} />
          </button>
        </div>
        <h3 style={{ margin: "24px 0 0", fontSize: 18, fontWeight: 700 }}>Summary</h3>
        <p style={{ margin: "6px 0 0", fontSize: 15, lineHeight: 1.6, color: "#3F3B31" }}>{doc.summary || "No summary for this document yet."}</p>
        {notes.length > 0 && (
          <>
            <div style={{ marginTop: 26, fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "#6F6857" }}>
              Linked Concepts ({notes.length})
            </div>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
              {notes.map((n, i) => (
                <div key={`${n.name}-${i}`} style={{ padding: "14px 16px", borderRadius: 10, background: "#F6F3EC" }}>
                  <div style={{ fontFamily: "var(--font-serif)", fontSize: 16, fontWeight: 600 }}>{n.name}</div>
                  {n.description && (
                    <div style={{ marginTop: 6, fontSize: 14, color: "#3F3B31" }}><MarkdownChat>{n.description}</MarkdownChat></div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
