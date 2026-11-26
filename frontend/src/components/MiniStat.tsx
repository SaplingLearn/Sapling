import React from "react";

export function MiniStat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="p-(--pad-md) border-r border-r-border min-w-0">
      <div className="label-micro">{label}</div>
      <div
        className="font-display text-3xl mt-0.5 [font-feature-settings:'lnum']" style={{ color: accent || "var(--text)" }}
      >
        {value}
      </div>
      {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}
