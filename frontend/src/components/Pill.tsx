"use client";
import React from "react";

export function Pill({
  children,
  active,
  onClick,
  icon,
  color,
}: {
  children: React.ReactNode;
  active?: boolean;
  onClick?: () => void;
  icon?: React.ReactNode;
  color?: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 11px",
        borderRadius: "var(--r-full)",
        fontSize: 12,
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
