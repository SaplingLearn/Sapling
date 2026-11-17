"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import { parsePlotSpec } from "./plotSpec";

/**
 * A fence that fails validation is shown as the code it is, never plotted
 * (the study-guide reader's FenceAsCode, in the chat's code-block style).
 */
function FenceAsCode({ spec }: { spec: string }) {
  return (
    <pre
      className="mono"
      data-testid="plot-fence-as-code"
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
      <code>{spec}</code>
    </pre>
  );
}

export function FunctionPlot({ spec }: { spec: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Every field function-plot sees comes from here, rebuilt from validated
  // tokens; a fence that fails never reaches it (see plotSpec.ts).
  const result = useMemo(() => parsePlotSpec(spec), [spec]);

  useEffect(() => {
    if (!result.ok) return;
    const parsed = result.spec;
    let cancelled = false;
    (async () => {
      try {
        const mod = await import("function-plot");
        const fp = (mod as { default: typeof mod.default }).default;
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = "";
        const width = Math.min(containerRef.current.clientWidth || 480, 560);
        fp({
          target: containerRef.current,
          width,
          height: Math.round(width * 0.6),
          grid: parsed.grid,
          title: parsed.title,
          xAxis: parsed.xAxis,
          yAxis: parsed.yAxis,
          data: parsed.data as never,
        });
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [result]);

  if (!result.ok) return <FenceAsCode spec={spec} />;

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
        {`Plot error: ${err}\n\n${spec}`}
      </pre>
    );
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={`Function plot: ${spec.replace(/\s+/g, " ").trim()}`}
      style={{
        margin: "10px 0 14px",
        padding: "8px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-sm)",
        overflowX: "auto",
        fontFamily: "var(--font-sans)",
      }}
    />
  );
}
