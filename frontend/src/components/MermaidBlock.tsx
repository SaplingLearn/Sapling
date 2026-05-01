"use client";

import React, { useEffect, useRef, useState } from "react";

let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        theme: "neutral",
        securityLevel: "strict",
        fontFamily: "var(--font-sans)",
      });
      return mod.default;
    });
  }
  return mermaidPromise;
}

let counter = 0;

// Mermaid 11.x's grammar for diamond labels (`{…}`) rejects unquoted text
// containing `=`, `?`, parens, etc. The tutor occasionally emits diamonds like
// `B{Is det(M) = 0?}` which fail to parse. Auto-quote diamond labels when they
// hold those characters and aren't already quoted, so the diagram renders.
// Other shapes (`[…]`, `(…)`, …) accept these characters unquoted.
const NEEDS_QUOTING = /[=?(),;]/;
function sanitizeMermaid(src: string): string {
  // Single-brace diamond `id{label}` only — the negative look-arounds keep us
  // out of hexagons (`id{{…}}`) and avoid over-matching across multiple braces
  // on one line. Label may not contain quotes or braces (so we don't re-wrap).
  return src.replace(
    /([A-Za-z][\w-]*)\{(?!\{)([^\n"{}]+)\}(?!\})/g,
    (match, id, label) => {
      if (!NEEDS_QUOTING.test(label)) return match;
      return `${id}{"${label}"}`;
    }
  );
}

export function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const idRef = useRef(`sap-mmd-${++counter}`);

  useEffect(() => {
    let cancelled = false;
    const safe = sanitizeMermaid(code);
    getMermaid()
      .then(async (mermaid) => {
        try {
          const { svg } = await mermaid.render(idRef.current, safe);
          if (!cancelled) setSvg(svg);
        } catch (e) {
          if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (err) {
    return (
      <pre
        className="mono"
        style={{
          padding: "10px 12px",
          color: "var(--err)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          background: "var(--bg-inset)",
          fontSize: 12,
          margin: "8px 0 12px",
          whiteSpace: "pre-wrap",
        }}
      >
        {`Mermaid error: ${err}\n\n${code}`}
      </pre>
    );
  }

  if (!svg) {
    return (
      <div style={{ padding: "10px 0", color: "var(--text-dim)", fontSize: 12, fontStyle: "italic" }}>
        Rendering diagram…
      </div>
    );
  }

  return (
    <div
      style={{ margin: "10px 0 14px", overflowX: "auto", textAlign: "center" }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
