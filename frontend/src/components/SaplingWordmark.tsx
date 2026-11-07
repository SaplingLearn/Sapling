import React from "react";

export const SAPLING_WORDMARK_SRC = "/design/sapling/originals/logo-letters.svg";

export const SAPLING_WORDMARK_LIGHT_SRC = "/design/sapling/originals/logo-letters.svg";

/** The full-colour logo for the light sidebar rail (sidebar handoff 7a):
 *  transparent PNG, letterforms #1D5C06, leaf #56A63A. Used only by
 *  `tone="full"`; every other surface keeps the original SVG above. */
export const SAPLING_LOGO_FULL_SRC = "/design/sapling/sapling-logo-v2.png";

const ASPECT = 395.02 / 1294.89;
const FULL_ASPECT = 388 / 1259;

export function SaplingWordmark({
  width,
  decorative = false,
  tone = "default",
  style,
  className,
}: {
  width: number;
  decorative?: boolean;
  tone?: "default" | "light" | "full";
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a static vector; next/image adds nothing for SVG
    <img
      src={
        tone === "full"
          ? SAPLING_LOGO_FULL_SRC
          : tone === "light"
            ? SAPLING_WORDMARK_LIGHT_SRC
            : SAPLING_WORDMARK_SRC
      }
      alt={decorative ? "" : "Sapling"}
      aria-hidden={decorative || undefined}
      width={width}
      height={Math.round(width * (tone === "full" ? FULL_ASPECT : ASPECT))}
      decoding="async"
      draggable={false}
      className={className}
      style={{
        display: "block",
        flexShrink: 0,
        width,
        height: "auto",
        ...(tone === "light" ? { filter: "brightness(0) invert(1)" } : {}),
        ...style,
      }}
    />
  );
}
