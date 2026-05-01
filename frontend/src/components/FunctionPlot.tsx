"use client";

import React, { useEffect, useRef, useState } from "react";

interface ParsedSpec {
  data: Array<Record<string, unknown>>;
  title?: string;
  xAxis?: { domain: [number, number] };
  yAxis?: { domain: [number, number] };
  grid?: boolean;
}

function parseDomain(val: string): [number, number] | null {
  const nums = val.match(/-?\d+(?:\.\d+)?/g);
  if (!nums || nums.length < 2) return null;
  return [Number(nums[0]), Number(nums[1])];
}

function parseSpec(input: string): ParsedSpec {
  const lines = input
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"));

  const data: Array<Record<string, unknown>> = [];
  const out: ParsedSpec = { data };

  for (const line of lines) {
    const m = line.match(/^([A-Za-z][\w-]*)\s*:\s*(.+)$/);
    if (!m) continue;
    const key = m[1].toLowerCase();
    const val = m[2].trim();

    if (key === "plot" || key === "fn") {
      const parts = val.split(/\s*;\s*/);
      const fn = parts[0];
      const meta: Record<string, unknown> = { fn };
      for (const p of parts.slice(1)) {
        const mm = p.match(/^(\w+)\s*=\s*(.+)$/);
        if (mm) {
          const k = mm[1].toLowerCase();
          const v = mm[2].trim();
          if (k === "color") meta.color = v;
          else if (k === "graphtype" || k === "type") meta.graphType = v;
          else if (k === "closed") meta.closed = v === "true";
        }
      }
      data.push(meta);
    } else if (key === "xdomain" || key === "x") {
      const d = parseDomain(val);
      if (d) out.xAxis = { domain: d };
    } else if (key === "ydomain" || key === "y") {
      const d = parseDomain(val);
      if (d) out.yAxis = { domain: d };
    } else if (key === "title") {
      out.title = val;
    } else if (key === "grid") {
      out.grid = val.toLowerCase() !== "false";
    }
  }

  if (out.grid === undefined) out.grid = true;
  return out;
}

export function FunctionPlot({ spec }: { spec: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mod = await import("function-plot");
        const fp = (mod as { default: typeof mod.default }).default;
        if (cancelled || !containerRef.current) return;
        const parsed = parseSpec(spec);
        if (parsed.data.length === 0) {
          setErr("No `plot:` line in spec");
          return;
        }
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
  }, [spec]);

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
