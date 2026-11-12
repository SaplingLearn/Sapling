"use client";
import React from "react";
import dynamic from "next/dynamic";
import type { Components } from "react-markdown";

// Lazy, to keep katex and highlight.js out of the server bundle (see
// ChatPanel.tsx for the rationale).
const MarkdownChat = dynamic(
  () => import("@/components/chat/MarkdownChat").then(m => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

/**
 * A guide's text is written by a model that read the student's documents, so
 * a document can put words into it. An image or an embedded frame fetches its
 * URL as soon as the guide is opened, and that URL can carry whatever the
 * text around it says. The reader draws neither.
 *
 * Links stay as the chat renderer draws them: followed only on a click, in a
 * new tab, without a referrer, and never to a script URL.
 */
const NOTHING_FETCHED: Components = { img: () => null, iframe: () => null };

/** Markdown and math for the reader's prose and formulas. */
export function Markdown({ children, components }: { children: string; components?: Components }) {
  const safe = React.useMemo(() => ({ ...components, ...NOTHING_FETCHED }), [components]);
  return <MarkdownChat components={safe}>{children}</MarkdownChat>;
}
