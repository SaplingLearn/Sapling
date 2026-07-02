"use client";
import React from "react";

type ChipVariant = "neutral" | "accent" | "warn" | "err" | "info";

// Shared chip/pill primitive for short status labels, tags, and filters.
// Maps to the .chip / .chip--* classes in globals.css (one radius, one type scale).
// For rarity/role/grade badges with a custom hue, use <Badge> instead.
export function Chip({
  variant = "neutral",
  icon,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: ChipVariant;
  icon?: React.ReactNode;
}) {
  const cls = ["chip", variant !== "neutral" && `chip--${variant}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={cls} {...props}>
      {icon}
      {children}
    </span>
  );
}
