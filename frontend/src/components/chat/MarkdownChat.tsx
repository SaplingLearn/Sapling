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

import {
  browserImageSrcContext,
  imageLinkHref,
  isAllowedMarkdownImageSrc,
} from "@/lib/markdownImages";
import { MermaidBlock } from "./MermaidBlock";
import { FunctionPlot } from "./FunctionPlot";
import { cn } from "@/lib/cn";

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
        // A GeoGebra material id is alphanumeric; anything else would put
        // model-chosen text into the frame URL.
        if (!id || !/^[A-Za-z0-9]{1,32}$/.test(id)) return;
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
  p: ({ children }) => <p className="mt-0 mx-0 mb-2">{children}</p>,
  strong: ({ children }) => (
    <strong className="text-text font-semibold">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => (
    <del className="line-through text-text-dim">{children}</del>
  ),
  ul: ({ children }) => <ul className="mt-1 mr-0 mb-2.5 ml-4.5 p-0">{children}</ul>,
  ol: ({ children }) => <ol className="mt-1 mr-0 mb-2.5 ml-5 p-0">{children}</ol>,
  li: ({ children, className }) => {
    const isTask = className?.includes("task-list-item");
    return (
      <li
        className={cn("my-0.5 mx-0", isTask ? "list-none" : "", isTask ? "-ml-4.5" : "")}
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
        className="mr-1.5 align-middle"
      />
    );
  },
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">
      {children}
    </a>
  ),
  // Only images the app serves are fetched (lib/markdownImages.ts): an
  // external image in model-written markdown is an exfiltration channel.
  // Anything else is offered as a link, followed only on a click.
  img: ({ src, alt }) => {
    const url = typeof src === "string" ? src : "";
    if (isAllowedMarkdownImageSrc(url, browserImageSrcContext())) {
      return (
        <img
          src={url}
          alt={alt || ""}
          loading="lazy"
          className="max-w-full h-auto rounded-sm border border-border my-1.5 mx-0 block"
        />
      );
    }
    const label = alt ? `[image: ${alt}]` : "[image]";
    const href = imageLinkHref(url);
    if (!href) return <span data-testid="markdown-image-blocked">{label}</span>;
    return (
      <a
        data-testid="markdown-image-blocked"
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        referrerPolicy="no-referrer"
        className="text-accent underline"
      >
        {label}
      </a>
    );
  },
  code: ({ children, className }) => {
    const inline = !className;
    if (inline) {
      return (
        <code
          className="mono py-px px-[5px] rounded-xs bg-bg-soft text-[length:0.9em]"
        >
          {children}
        </code>
      );
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ children }) => (
    <pre
      className="mono py-2.5 px-3 rounded-sm bg-bg-inset border border-border overflow-x-auto text-sm mt-1.5 mx-0 mb-2.5"
    >
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    // Italic body-serif instead of a side-tab accent border (which is the
    // #1 AI-dashboard tell). The brand's hierarchy should come from type.
    <blockquote
      className="body-serif mt-1.5 mx-0 mb-3 pt-0.5 pr-0 pb-0.5 pl-3 text-text-dim italic"
    >
      {children}
    </blockquote>
  ),
  h1: ({ children }) => <h1 className="h-serif text-xl mt-2 mx-0 mb-1.5">{children}</h1>,
  h2: ({ children }) => <h2 className="h-serif text-lg mt-2 mx-0 mb-1.5">{children}</h2>,
  h3: ({ children }) => <h3 className="h-serif text-base mt-1.5 mx-0 mb-1">{children}</h3>,
  hr: () => <hr className="border-0 border-t border-t-border my-3 mx-0" />,
  table: ({ children }) => (
    <div className="overflow-x-auto mt-2 mx-0 mb-3">
      <table
        className="border-collapse w-full text-md font-sans"
      >
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-bg-subtle">{children}</thead>,
  th: ({ children, style }) => (
    <th
      className="text-left py-1.5 px-2.5 border-b border-b-border-strong font-semibold" style={{ ...style }}
    >
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td
      className="py-1.5 px-2.5 border-b border-b-border align-top" style={{ ...style }}
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
          className="mt-2.5 mx-0 mb-3.5 py-2.5 px-3.5 rounded-sm" style={{ background: isWarn ? "var(--warn-soft)" : isProof ? "transparent" : "var(--bg-subtle)", border: `1px ${isProof ? "dashed" : "solid"} ${isWarn ? "var(--warn)" : "var(--border)"}` }}
        >
          {!classes.includes("sap-callout__rendered-title") && label ? (
            <div
              className={cn("font-sans text-md font-bold mb-1", isWarn ? "text-warn" : "text-accent")}
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
          className="font-sans text-sm font-semibold text-text mb-1 italic"
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
        className={cn("border border-border rounded-sm max-w-full block", isGeo ? "mt-2.5 mx-0 mb-3.5" : "")}
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
    <div className="leading-[1.55]">
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
