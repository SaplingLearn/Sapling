"use client";
import React from "react";

// Shared badge for rarity / role / grade — anywhere a pill is tinted from a single
// base hue. Reuses .chip for shape + typography. The HUE is carried by the border +
// a soft background; the TEXT stays neutral (--text) because colored text on a tinted
// pill fails 4.5:1 contrast on several tiers (the rule the rarity badges already follow).
export function Badge({
  color = "var(--border)",
  bg,
  className,
  children,
  style,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  color?: string; // the hue (border)
  bg?: string; // optional explicit soft background; derived from `color` if omitted
}) {
  return (
    <span
      className={["chip", className].filter(Boolean).join(" ")}
      style={{
        borderColor: color,
        background: bg ?? `color-mix(in oklab, ${color} 12%, var(--bg-panel))`,
        color: "var(--text)",
        ...style,
      }}
      {...props}
    >
      {children}
    </span>
  );
}
