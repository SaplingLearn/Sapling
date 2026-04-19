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
    <div style={{ padding: "var(--pad-md)", borderRight: "1px solid var(--border)", minWidth: 0 }}>
      <div className="label-micro">{label}</div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 26,
          marginTop: 2,
          color: accent || "var(--text)",
          fontFeatureSettings: '"lnum"',
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
