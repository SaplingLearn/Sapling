import React from "react";

/** The approved Pen wordmark (from #728), its two stroke colours moved onto
 *  the olive brand: letterforms #445d22 (--brand-forest), leaf #71983c. */
export const SAPLING_WORDMARK_SRC = "/design/sapling/sapling-wordmark-approved.svg";

/** The same drawing recoloured cream (strokes #faf8f3, leaf #c5d7b2) for the
 *  olive SideNav rail, where the approved dark-green strokes disappear. Only
 *  the two stroke colours differ from the approved file. */
export const SAPLING_WORDMARK_LIGHT_SRC = "/design/sapling/sapling-wordmark-light.svg";

/** The file's own viewBox, 150 × 44.55. */
const ASPECT = 44.55 / 150;

/**
 * The Sapling logo: the hand-drawn wordmark whose leaf dots the "i". It is the
 * whole lockup, so it replaces the old sprout icon + set "Sapling" text rather
 * than sitting beside them.
 *
 * Decorative when the surrounding link already carries the name. `tone="light"`
 * swaps in the cream recolour for dark surfaces.
 */
export function SaplingWordmark({
  width,
  decorative = false,
  tone = "default",
  style,
  className,
}: {
  width: number;
  decorative?: boolean;
  tone?: "default" | "light";
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG
    <img
      src={tone === "light" ? SAPLING_WORDMARK_LIGHT_SRC : SAPLING_WORDMARK_SRC}
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
