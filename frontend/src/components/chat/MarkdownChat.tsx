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
import { INERT_COMPONENTS, type MarkdownProfile } from "./inertMarkdown";
import { GEOGEBRA_ORIGIN } from "@/lib/securityHeaders";
import styles from "./MarkdownChat.module.css";

/** A GeoGebra applet's frame size (the `::geogebra` directive), px. */
const GEOGEBRA_FRAME = { width: 480, height: 360 } as const;

// Castel-style shortcuts. Tutor can write `\R` instead of `\mathbb{R}`.
// Frozen and never handed to KaTeX itself: KaTeX writes every \gdef / \global
// definition into the macros object it is given (Z32).
const KATEX_MACROS: Readonly<Record<string, string>> = Object.freeze({
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
});

// The table every "rich" render shares, as on main: a definition one rich
// message makes carries into the next (the loop-off app renders exactly as
// before). An "inert" render — class material the learning loop serves
// verbatim — gets its own copy of the pristine table instead, so its \gdef
// stays in that message and no other message's reaches it (Z32).
const SHARED_KATEX_MACROS: Record<string, string> = { ...KATEX_MACROS };

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
          // The CSP's frame-src names the same origin (lib/securityHeaders.ts).
          src: `${GEOGEBRA_ORIGIN}/material/iframe/id/${id}`,
          width: GEOGEBRA_FRAME.width,
          height: GEOGEBRA_FRAME.height,
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
  p: ({ children }) => <p className={styles.p}>{children}</p>,
  strong: ({ children }) => <strong className={styles.strong}>{children}</strong>,
  em: ({ children }) => <em className={styles.em}>{children}</em>,
  del: ({ children }) => <del className={styles.del}>{children}</del>,
  ul: ({ children }) => <ul className={styles.ul}>{children}</ul>,
  ol: ({ children }) => <ol className={styles.ol}>{children}</ol>,
  li: ({ children, className }) => {
    const isTask = className?.includes("task-list-item");
    return <li className={isTask ? `${styles.li} ${styles.taskItem}` : styles.li}>{children}</li>;
  },
  input: ({ type, checked, disabled }) => {
    if (type !== "checkbox") return null;
    return (
      <input
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        readOnly
        className={styles.checkbox}
      />
    );
  },
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className={styles.link}>
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
          className={styles.img}
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
        className={styles.link}
      >
        {label}
      </a>
    );
  },
  code: ({ children, className }) => {
    const inline = !className;
    if (inline) {
      return (
        <code className={`mono ${styles.code}`}>
          {children}
        </code>
      );
    }
    return <code className={className}>{children}</code>;
  },
  pre: ({ children }) => (
    <pre className={`mono ${styles.pre}`}>
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    // Italic body-serif instead of a side-tab accent border (which is the
    // #1 AI-dashboard tell). The brand's hierarchy should come from type.
    <blockquote className={`body-serif ${styles.blockquote}`}>
      {children}
    </blockquote>
  ),
  h1: ({ children }) => <h1 className={`h-serif ${styles.h1}`}>{children}</h1>,
  h2: ({ children }) => <h2 className={`h-serif ${styles.h2}`}>{children}</h2>,
  h3: ({ children }) => <h3 className={`h-serif ${styles.h3}`}>{children}</h3>,
  hr: () => <hr className={styles.hr} />,
  table: ({ children }) => (
    <div className={styles.tableWrap}>
      <table className={styles.table}>{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className={styles.thead}>{children}</thead>,
  // `style`: a GFM column's alignment, from the markdown itself.
  th: ({ children, style }) => (
    <th className={styles.th} style={style}>
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td className={styles.td} style={style}>
      {children}
    </td>
  ),
  div: ({ children, className, ...rest }) => {
    const classes = Array.isArray(className) ? className.join(" ") : className || "";
    if (classes.includes("sap-callout")) {
      const name = (rest as Record<string, unknown>)["data-callout"] as string | undefined;
      const label = (name && CALLOUT_LABEL[name]) || "";
      // `data-callout` picks the warning / proof treatment in the module.
      return (
        <div className={styles.callout} data-callout={name}>
          {!classes.includes("sap-callout__rendered-title") && label ? (
            <div className={styles.calloutLabel}>
              {label}
            </div>
          ) : null}
          {children}
        </div>
      );
    }
    if (classes.includes("sap-callout__title")) {
      return (
        <div className={styles.calloutTitle}>
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
        className={styles.iframe}
        data-geogebra={isGeo}
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
  profile = "rich",
}: {
  children: string;
  components?: Components;
  /** "inert" (Z08, `inertMarkdown.tsx`): text that may repeat class material
   *  verbatim — no directive syntax, links as text naming their host, no
   *  image fetched, nothing embedded, no diagram drawn. */
  profile?: MarkdownProfile;
}) {
  const inert = profile === "inert";
  return (
    <div className="leading-[1.55]">
      <ReactMarkdown
        remarkPlugins={
          inert
            ? [remarkGfm, remarkMath] // a "::geogebra{…}" line stays text
            : [remarkGfm, remarkMath, remarkDirective, remarkSaplingDirectives]
        }
        rehypePlugins={[
          // Z32: inert, a fresh copy of the pristine table per render
          [rehypeKatex, { macros: inert ? { ...KATEX_MACROS } : SHARED_KATEX_MACROS, strict: "ignore" }],
          rehypeExtractDiagramBlocks,
          [rehypeHighlight, { detect: true, ignoreMissing: true }],
        ]}
        components={
          inert
            ? { ...COMPONENTS, ...(components || {}), ...INERT_COMPONENTS }
            : { ...COMPONENTS, ...(components || {}) }
        }
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
