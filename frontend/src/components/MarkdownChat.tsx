"use client";

import React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import remarkDirective from "remark-directive";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import { visit } from "unist-util-visit";
import "katex/dist/katex.min.css";
import "katex/contrib/mhchem";
import "highlight.js/styles/github.css";

import { MermaidBlock } from "./MermaidBlock";
import { FunctionPlot } from "./FunctionPlot";

// Castel-style shortcuts. Tutor can write `\R` instead of `\mathbb{R}`.
const KATEX_MACROS: Record<string, string> = {
  "\\R": "\\mathbb{R}",
  "\\Z": "\\mathbb{Z}",
  "\\N": "\\mathbb{N}",
  "\\Q": "\\mathbb{Q}",
  "\\C": "\\mathbb{C}",
  "\\F": "\\mathbb{F}",
  "\\E": "\\mathbb{E}",
  "\\Pr": "\\mathbb{P}",
  "\\norm": "\\left\\lVert #1 \\right\\rVert",
  "\\abs": "\\left\\lvert #1 \\right\\rvert",
  "\\set": "\\left\\{ #1 \\right\\}",
  "\\inner": "\\left\\langle #1 \\right\\rangle",
  "\\Var": "\\operatorname{Var}",
  "\\Cov": "\\operatorname{Cov}",
  "\\Tr": "\\operatorname{Tr}",
  "\\rank": "\\operatorname{rank}",
  "\\diag": "\\operatorname{diag}",
  "\\eps": "\\varepsilon",
  "\\dx": "\\,dx",
  "\\dy": "\\,dy",
  "\\dt": "\\,dt",
};

const CALLOUT_NAMES = new Set([
  "theorem",
  "definition",
  "proof",
  "lemma",
  "corollary",
  "proposition",
  "example",
  "remark",
  "note",
  "tip",
  "warning",
]);

const CALLOUT_LABEL: Record<string, string> = {
  theorem: "Theorem",
  definition: "Definition",
  proof: "Proof",
  lemma: "Lemma",
  corollary: "Corollary",
  proposition: "Proposition",
  example: "Example",
  remark: "Remark",
  note: "Note",
  tip: "Tip",
  warning: "Warning",
};

// remark plugin: convert :::theorem/::geogebra/etc. directives to hast nodes
function remarkSaplingDirectives() {
  return (tree: unknown) => {
    visit(tree as never, (node: never) => {
      const n = node as {
        type?: string;
        name?: string;
        attributes?: Record<string, string | undefined>;
        children?: Array<{ type?: string; data?: { directiveLabel?: boolean; hName?: string; hProperties?: Record<string, unknown> } }>;
        data?: { hName?: string; hProperties?: Record<string, unknown> };
      };

      if (n.type === "containerDirective" && n.name && CALLOUT_NAMES.has(n.name)) {
        const data = n.data || (n.data = {});
        data.hName = "div";
        data.hProperties = {
          className: ["sap-callout", `sap-callout--${n.name}`],
          "data-callout": n.name,
        };
        const first = n.children?.[0];
        if (first?.type === "paragraph" && first.data?.directiveLabel) {
          first.data.hName = "div";
          first.data.hProperties = { className: ["sap-callout__title"] };
        }
      }

      if (n.type === "leafDirective" && n.name === "geogebra") {
        const id = n.attributes?.id || n.attributes?.materialid || n.attributes?.material;
        if (!id) return;
        const data = n.data || (n.data = {});
        data.hName = "iframe";
        data.hProperties = {
          src: `https://www.geogebra.org/material/iframe/id/${id}`,
          width: 480,
          height: 360,
          frameBorder: 0,
          allowFullScreen: true,
          loading: "lazy",
          className: ["sap-geogebra"],
        };
      }
    });
  };
}

// rehype plugin: extract mermaid/plot fences BEFORE rehype-highlight runs.
// Replaces <pre><code class="language-mermaid">…</code></pre> with a custom
// element so we can render it via a React component instead of highlighting it.
function rehypeExtractDiagramBlocks() {
  return (tree: unknown) => {
    visit(
      tree as never,
      "element",
      (node: never, index: number | undefined, parent: never) => {
        const el = node as {
          tagName?: string;
          children?: Array<{
            tagName?: string;
            properties?: { className?: string[] | string };
            children?: Array<{ value?: string }>;
          }>;
        };
        const par = parent as { children?: unknown[] } | null;
        if (el.tagName !== "pre" || !par || index === undefined) return;
        const codeChild = el.children?.[0];
        if (codeChild?.tagName !== "code") return;
        const cls = codeChild.properties?.className;
        const classes = Array.isArray(cls) ? cls : typeof cls === "string" ? [cls] : [];
        const langClass = classes.find((c) => typeof c === "string" && c.startsWith("language-"));
        if (!langClass) return;
        const lang = langClass.slice(9);
        if (lang !== "mermaid" && lang !== "plot" && lang !== "function-plot") return;
        const raw = codeChild.children?.[0]?.value || "";
        const tagName = lang === "mermaid" ? "sap-mermaid" : "sap-plot";
        (par.children as unknown[])[index] = {
          type: "element",
          tagName,
          properties: { "data-content": raw },
          children: [],
        };
      }
    );
  };
}

const COMPONENTS: Components = {
  p: ({ children }) => <p style={{ margin: "0 0 8px" }}>{children}</p>,
  strong: ({ children }) => (
    <strong style={{ color: "var(--text)", fontWeight: 600 }}>{children}</strong>
  ),
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
  hr: () => <hr style={{ border: 0, borderTop: "1px solid var(--border)", margin: "12px 0" }} />,
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
  thead: ({ children }) => <thead style={{ background: "var(--bg-subtle)" }}>{children}</thead>,
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
  div: ({ children, className, ...rest }) => {
    const classes = Array.isArray(className) ? className.join(" ") : className || "";
    if (classes.includes("sap-callout")) {
      const name = (rest as Record<string, unknown>)["data-callout"] as string | undefined;
      const label = (name && CALLOUT_LABEL[name]) || "";
      const isWarn = name === "warning";
      const isProof = name === "proof";
      return (
        <div
          style={{
            margin: "10px 0 14px",
            padding: "10px 14px",
            background: isWarn ? "var(--warn-soft)" : isProof ? "transparent" : "var(--bg-subtle)",
            border: `1px ${isProof ? "dashed" : "solid"} ${isWarn ? "var(--warn)" : "var(--border)"}`,
            borderRadius: "var(--r-sm)",
          }}
        >
          {!classes.includes("sap-callout__rendered-title") && label ? (
            <div
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: isWarn ? "var(--warn)" : "var(--accent)",
                fontWeight: 700,
                marginBottom: 4,
              }}
            >
              {label}
            </div>
          ) : null}
          {children}
        </div>
      );
    }
    if (classes.includes("sap-callout__title")) {
      return (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text)",
            marginBottom: 4,
            fontStyle: "italic",
          }}
        >
          {children}
        </div>
      );
    }
    return <div className={className}>{children}</div>;
  },
  iframe: ({ src, width, height, className }) => {
    const classes = Array.isArray(className) ? className.join(" ") : className || "";
    const isGeo = classes.includes("sap-geogebra");
    return (
      <iframe
        src={typeof src === "string" ? src : undefined}
        width={width}
        height={height}
        loading="lazy"
        allowFullScreen
        style={{
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          maxWidth: "100%",
          margin: isGeo ? "10px 0 14px" : undefined,
          display: "block",
        }}
      />
    );
  },
  // Custom tag names emitted by rehypeExtractDiagramBlocks. Cast around
  // Components type since it doesn't allow arbitrary tags.
  ...({
    "sap-mermaid": (props: { "data-content"?: string }) => (
      <MermaidBlock code={props["data-content"] || ""} />
    ),
    "sap-plot": (props: { "data-content"?: string }) => (
      <FunctionPlot spec={props["data-content"] || ""} />
    ),
  } as unknown as Components),
};

export const MarkdownChat = React.memo(function MarkdownChat({
  children,
  components,
}: {
  children: string;
  components?: Components;
}) {
  return (
    <div style={{ lineHeight: 1.55 }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkDirective, remarkSaplingDirectives]}
        rehypePlugins={[
          [rehypeKatex, { macros: KATEX_MACROS, strict: "ignore" }],
          rehypeExtractDiagramBlocks,
          [rehypeHighlight, { detect: true, ignoreMissing: true }],
        ]}
        components={{ ...COMPONENTS, ...(components || {}) }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
