"use client";

import React from "react";
import type { Role } from "@/lib/types";

interface RoleBadgeProps {
  role: Role;
  size?: "sm" | "md";
  showIcon?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function RoleBadge({ role, size = "sm", showIcon = true, className, style }: RoleBadgeProps) {
  const color = role.color || "var(--text-muted)";
  const fontSize = size === "sm" ? 10 : 11;
  const padding = size === "sm" ? "2px 7px" : "3px 9px";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding,
        fontSize,
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        borderRadius: "var(--r-full)",
        color,
        background: `color-mix(in oklab, ${color} 14%, transparent)`,
        border: `1px solid color-mix(in oklab, ${color} 28%, transparent)`,
        ...style,
      }}
    >
      {showIcon && role.icon && <span aria-hidden>{role.icon}</span>}
      <span>{role.name}</span>
    </span>
  );
}
