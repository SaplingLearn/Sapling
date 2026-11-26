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
      className="mono py-2.5 px-3 rounded-sm bg-bg-inset border border-border overflow-x-auto text-sm mt-1.5 mx-0 mb-2.5"
      data-testid="plot-fence-as-code"
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
        className="mono py-2.5 px-3 text-err border border-border rounded-sm bg-bg-inset text-sm mt-2 mx-0 mb-3 whitespace-pre-wrap"
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
      className="mt-2.5 mx-0 mb-3.5 p-2 bg-bg-panel border border-border rounded-sm overflow-x-auto font-sans"
    />
  );
}
