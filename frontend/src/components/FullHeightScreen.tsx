"use client";

import React from "react";

/**
 * Full-height root for screens rendered inside `ShellFrame`'s `<main>`.
 *
 * ShellFrame's horizontal-nav layout stacks the 56px `TopNav` above `<main>`
 * in a `100dvh` flex column, so `<main>` is only `100dvh - 56px` tall. Screens
 * that hardcoded `height: 100vh` were therefore taller than their container,
 * which overflowed `<main>` and made the whole page scroll — dragging chat
 * headers/inputs out of view instead of scrolling just the body (issue #331).
 *
 * Filling the parent with `height: 100%` pins the screen to `<main>` exactly,
 * so inner regions scroll internally. `<main>` has a definite height in both
 * the sidebar and top-nav layouts, so the percentage resolves correctly in
 * each — keeping the sidebar layout unaffected.
 *
 * Use this instead of `height: 100vh` for any full-height shell screen.
 */
export function FullHeightScreen({
  children,
  direction = "column",
  className,
  style,
}: {
  children: React.ReactNode;
  /** Flex direction of the root. Defaults to "column". */
  direction?: "row" | "column";
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: direction,
        height: "100%",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
