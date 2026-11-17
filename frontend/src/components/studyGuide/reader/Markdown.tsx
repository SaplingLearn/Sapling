"use client";
import React from "react";
import dynamic from "next/dynamic";
import type { Components } from "react-markdown";

import s from "./reader.module.css";

// Lazy, to keep katex and highlight.js out of the server bundle (see
// ChatPanel.tsx for the rationale).
const MarkdownChat = dynamic(
  () => import("@/components/chat/MarkdownChat").then(m => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

/**
 * The chat draws a ```mermaid fence as a diagram and a ```plot fence as a
 * plot, and a diagram's text can name an image that drawing it fetches. The
 * reader shows either fence as the code it is.
 */
function FenceAsCode({ "data-content": code }: { "data-content"?: string }) {
  return (
    <pre className={s.code}>
      <code>{code ?? ""}</code>
    </pre>
  );
}

/**
 * A guide's text is written by a model that read the student's documents, so
 * a document can put words into it. An image, an embedded frame or a drawn
 * diagram fetches its URL as soon as the guide is opened, and that URL can
 * carry whatever the text around it says. The reader draws none of them.
 *
 * Links stay as the chat renderer draws them: followed only on a click, in a
 * new tab, without a referrer, and never to a script URL.
 */
const NOTHING_FETCHED = {
  img: () => null,
  iframe: () => null,
  // The chat's names for the elements it turns those two fences into.
  "sap-mermaid": FenceAsCode,
  "sap-plot": FenceAsCode,
} as unknown as Components;

/** Markdown and math for the reader's prose and formulas. */
export function Markdown({ children, components }: { children: string; components?: Components }) {
  const safe = React.useMemo(() => ({ ...components, ...NOTHING_FETCHED }), [components]);
  return <MarkdownChat components={safe}>{children}</MarkdownChat>;
}
