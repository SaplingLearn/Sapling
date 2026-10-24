import type React from "react";

/** Shared admin-console input style (text inputs, textareas). */
export const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-sm)",
  fontSize: 13,
  background: "var(--bg-input)",
  fontFamily: "inherit",
};

/** Admin table header cell. */
export const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 16px",
  fontWeight: 500,
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--text-muted)",
};

/** Admin table body cell. */
export const tdStyle: React.CSSProperties = { padding: "10px 16px" };
