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
// is open". Leave `size` at its default on a link: `.btn--sm`/`--lg`/`--xl`
// still apply their padding, which is the shape `link` exists to shed.
//
// The ref is forwarded so callers can hold the DOM node: the quiz's question
// screen needs "Ask about this" as a return-focus target when its Sheet
// closes, and was otherwise forced to drop to a raw `<button className="btn">`
// to get one. Nothing else about the component changes.
export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, type = "button", ...props },
  ref,
) {
  const cls = [
    "btn",
    variant !== "secondary" && `btn--${variant}`,
    size !== "md" && `btn--${size}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return <button ref={ref} type={type} className={cls} {...props} />;
});
