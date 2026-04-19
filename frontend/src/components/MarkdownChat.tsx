"use client";

import React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

const COMPONENTS: Components = {
  p: ({ children }) => <p style={{ margin: "0 0 8px" }}>{children}</p>,
  strong: ({ children }) => <strong style={{ color: "var(--text)", fontWeight: 600 }}>{children}</strong>,
  em: ({ children }) => <em style={{ fontStyle: "italic" }}>{children}</em>,
  ul: ({ children }) => <ul style={{ margin: "4px 0 10px 18px", padding: 0 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: "4px 0 10px 20px", padding: 0 }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: "2px 0" }}>{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", textDecoration: "underline" }}>
      {children}
    </a>
  ),
  code: ({ children, className }) => {
    const inline = !className;
    if (inline) {
      return (
        <code
          className="mono"
          style={{
            padding: "1px 5px",
            borderRadius: "var(--r-xs)",
            background: "var(--bg-soft)",
            fontSize: "0.9em",
          }}
        >
          {children}
        </code>
      );
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ children }) => (
    <pre
      className="mono"
      style={{
        padding: "10px 12px",
        borderRadius: "var(--r-sm)",
        background: "var(--bg-inset)",
        border: "1px solid var(--border)",
        overflowX: "auto",
        fontSize: 12,
        margin: "6px 0 10px",
      }}
    >
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    // Italic body-serif instead of a side-tab accent border (which is the
    // #1 AI-dashboard tell). The brand's hierarchy should come from type.
    <blockquote
      className="body-serif"
      style={{
        margin: "6px 0 12px",
        padding: "2px 0 2px 12px",
        color: "var(--text-dim)",
        fontStyle: "italic",
      }}
    >
      {children}
    </blockquote>
  ),
  h1: ({ children }) => <h1 className="h-serif" style={{ fontSize: 18, margin: "8px 0 6px" }}>{children}</h1>,
  h2: ({ children }) => <h2 className="h-serif" style={{ fontSize: 16, margin: "8px 0 6px" }}>{children}</h2>,
  h3: ({ children }) => <h3 className="h-serif" style={{ fontSize: 14, margin: "6px 0 4px" }}>{children}</h3>,
};

export function MarkdownChat({ children, components }: { children: string; components?: Components }) {
  return (
    <div style={{ lineHeight: 1.55 }}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{ ...COMPONENTS, ...(components || {}) }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
