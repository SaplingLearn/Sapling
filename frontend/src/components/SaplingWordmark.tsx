import React from "react";

/** The approved Pen wordmark (from #728), byte-for-byte. */
export const SAPLING_WORDMARK_SRC = "/design/sapling/sapling-wordmark-approved.svg";

/** The file's own viewBox, 150 × 44.55. */
const ASPECT = 44.55 / 150;

/**
 * The Sapling logo: the hand-drawn wordmark whose leaf dots the "i". It is the
 * whole lockup, so it replaces the old sprout icon + set "Sapling" text rather
 * than sitting beside them.
 *
 * Decorative when the surrounding link already carries the name.
 */
export function SaplingWordmark({
  width,
  decorative = false,
  style,
  className,
}: {
  width: number;
  decorative?: boolean;
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG
    <img
      src={SAPLING_WORDMARK_SRC}
      alt={decorative ? "" : "Sapling"}
      aria-hidden={decorative || undefined}
      width={width}
      height={Math.round(width * ASPECT)}
      decoding="async"
      draggable={false}
      className={className}
      style={{
        display: "block",
        flexShrink: 0,
        width,
        height: "auto",
        ...style,
      }}
    />
  );
}
