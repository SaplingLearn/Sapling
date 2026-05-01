"use client";

import React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import "katex/dist/katex.min.css";
import "highlight.js/styles/github.css";

const COMPONENTS: Components = {
  p: ({ children }) => <p style={{ margin: "0 0 8px" }}>{children}</p>,
  strong: ({ children }) => <strong style={{ color: "var(--text)", fontWeight: 600 }}>{children}</strong>,
  em: ({ children }) => <em style={{ fontStyle: "italic" }}>{children}</em>,
  del: ({ children }) => (
    <del style={{ textDecoration: "line-through", color: "var(--text-dim)" }}>{children}</del>
  ),
  ul: ({ children }) => <ul style={{ margin: "4px 0 10px 18px", padding: 0 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: "4px 0 10px 20px", padding: 0 }}>{children}</ol>,
  li: ({ children, className }) => {
    const isTask = className?.includes("task-list-item");
    return (
      <li
        style={{
          margin: "2px 0",
          listStyle: isTask ? "none" : undefined,
          marginLeft: isTask ? -18 : undefined,
        }}
      >
        {children}
      </li>
    );
  },
  input: ({ type, checked, disabled }) => {
    if (type !== "checkbox") return null;
    return (
      <input
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        readOnly
        style={{ marginRight: 6, verticalAlign: "middle" }}
      />
    );
  },
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: "var(--accent)", textDecoration: "underline" }}>
      {children}
    </a>
  ),
  img: ({ src, alt }) => (
    <img
      src={typeof src === "string" ? src : undefined}
      alt={alt || ""}
      style={{
        maxWidth: "100%",
        height: "auto",
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--border)",
        margin: "6px 0",
        display: "block",
      }}
    />
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
  hr: () => (
    <hr style={{ border: 0, borderTop: "1px solid var(--border)", margin: "12px 0" }} />
  ),
  table: ({ children }) => (
    <div style={{ overflowX: "auto", margin: "8px 0 12px" }}>
      <table
        style={{
          borderCollapse: "collapse",
          width: "100%",
          fontSize: 13,
          fontFamily: "var(--font-sans)",
        }}
      >
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead style={{ background: "var(--bg-subtle)" }}>{children}</thead>
  ),
  th: ({ children, style }) => (
    <th
      style={{
        textAlign: "left",
        padding: "6px 10px",
        borderBottom: "1px solid var(--border-strong)",
        fontWeight: 600,
        ...style,
      }}
    >
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td
      style={{
        padding: "6px 10px",
        borderBottom: "1px solid var(--border)",
        verticalAlign: "top",
        ...style,
      }}
    >
      {children}
    </td>
  ),
};

export function MarkdownChat({ children, components }: { children: string; components?: Components }) {
  return (
    <div style={{ lineHeight: 1.55 }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, [rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{ ...COMPONENTS, ...(components || {}) }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
