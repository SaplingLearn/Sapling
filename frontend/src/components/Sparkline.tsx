import React from "react";

export function Sparkline({
  data,
  w = 80,
  h = 24,
  color = "var(--accent)",
}: {
  data: number[];
  w?: number;
  h?: number;
  color?: string;
}) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / (max - min || 1)) * h}`).join(" ");
  return (
    <svg width={w} height={h}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  );
}
