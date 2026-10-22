"use client";
import React from "react";

export function Pill({
  children,
  active,
  onClick,
  icon,
  color,
  testId,
  size = "sm",
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
  icon?: React.ReactNode;
  color?: string;
  testId?: string;
  /** `sm` (default) is the filter-row pill everywhere else; `md` sits beside
   *  body-size text, as quiz home's course pills do. */
  size?: "sm" | "md";
}) {
  const md = size === "md";
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: md ? "7px 15px" : "5px 11px",
        borderRadius: "var(--r-full)",
        fontSize: md ? 14 : 12,
        background: active ? (color || "var(--accent-soft)") : "transparent",
        color: active ? (color ? "#fff" : "var(--accent)") : "var(--text-dim)",
        border: `1px solid ${active ? (color || "var(--accent-border)") : "var(--border)"}`,
        transition: "all var(--dur-fast) var(--ease)",
        fontFamily: "var(--font-sans)",
      }}
    >
      {icon}
      {children}
    </button>
  );
}
