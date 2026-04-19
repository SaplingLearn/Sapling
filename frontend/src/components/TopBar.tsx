import React from "react";

export function TopBar({
  title,
  subtitle,
  actions,
  breadcrumb,
}: {
  // Title is optional now — the Dashboard uses a centered hero block
  // below the TopBar for its greeting, so the bar itself just shows
  // the breadcrumb + actions.
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  const hasTitle = title !== undefined && title !== null && title !== "";
  return (
    <header
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        padding: hasTitle ? "22px 32px 16px" : "16px 32px",
        borderBottom: "1px solid var(--border)",
        background: "var(--bg)",
        position: "sticky",
        top: 0,
        zIndex: 5,
      }}
    >
      <div>
        {breadcrumb && <div className="label-micro" style={{ marginBottom: hasTitle ? 4 : 0 }}>{breadcrumb}</div>}
        {hasTitle && (
          <h1 className="h-serif" style={{ margin: 0, fontSize: 30, fontWeight: 500 }}>{title}</h1>
        )}
        {subtitle && <div style={{ color: "var(--text-dim)", marginTop: 4, fontSize: 13 }}>{subtitle}</div>}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>{actions}</div>
    </header>
  );
}
