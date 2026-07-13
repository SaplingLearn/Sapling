"use client";
import React from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg" | "xl";

// Shared button primitive. Wraps the canonical .btn classes in globals.css so
// every action button is one shape (6px) with consistent hover/transitions.
// - variant: primary (forest fill) | secondary (bordered, default) | ghost | danger
// - size:    sm | md (default) | lg (the hero size for de-pilled CTAs)
// Pills are NOT a Button — use <Toggle> for segmented controls.
export function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
}) {
  const cls = [
    "btn",
    variant !== "secondary" && `btn--${variant}`,
    size !== "md" && `btn--${size}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return <button type={type} className={cls} {...props} />;
}
