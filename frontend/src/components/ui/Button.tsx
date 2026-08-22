"use client";
import React from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";
type Size = "sm" | "md" | "lg" | "xl";

// Shared button primitive. Wraps the canonical .btn classes in globals.css so
// every action button is one shape (6px) with consistent hover/transitions.
// - variant: primary (forest fill) | secondary (bordered, default) | ghost |
//            danger | link
// - size:    sm | md (default) | lg (the hero size for de-pilled CTAs)
// Pills are NOT a Button — use <Toggle> for segmented controls.
//
// `link` is a bare text button — no padding, border or background, muted until
// hover. It exists because "adjust", "Discard", "Pick something specific →"
// and "Done" are text, not chrome, and `ghost` keeps button padding so it
// still reads as a control (#537). `aria-pressed` / `data-active="true"`
// underlines it in the accent, which is how the quiz shows "this link's dialog
// is open". `size` is ignored by `link`: it has no padding to scale.
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
