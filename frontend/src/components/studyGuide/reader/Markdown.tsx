"use client";
import dynamic from "next/dynamic";

// Lazy, to keep katex and highlight.js out of the server bundle (see
// ChatPanel.tsx for the rationale).
export const Markdown = dynamic(
  () => import("@/components/chat/MarkdownChat").then(m => m.MarkdownChat),
  { ssr: false, loading: () => null },
);
