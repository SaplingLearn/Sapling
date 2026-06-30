"use client";
import React from "react";

// Shared badge for rarity / role / grade — anywhere a pill is tinted from a single
// base hue. Reuses .chip for shape + typography and derives bg/border from `color`
// via color-mix, centralizing the logic duplicated across RoleBadge / TitleFlair /
// the Achievements inline badges.
export function Badge({
  color = "var(--text-dim)",
  className,
  children,
  style,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  color?: string;
}) {
  return (
    <span
      className={["chip", className].filter(Boolean).join(" ")}
      style={{
        background: `color-mix(in oklab, ${color} 12%, var(--bg-panel))`,
        color,
        borderColor: `color-mix(in oklab, ${color} 35%, transparent)`,
        ...style,
      }}
      {...props}
    >
      {children}
    </span>
  );
}
