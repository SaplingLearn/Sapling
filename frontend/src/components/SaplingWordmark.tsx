import React from "react";

/** The wordmark (jack_h.v2): one raster everywhere, so the landing, the app
 *  chrome and onboarding all show the same mark. */
export const SAPLING_WORDMARK_SRC = "/sapling-wordmark.png";

export const SAPLING_WORDMARK_LIGHT_SRC = "/sapling-wordmark.png";

const ASPECT = 384 / 1255;

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
    // eslint-disable-next-line @next/next/no-img-element -- a static asset sized by the caller
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
        ...(tone === "light" ? { filter: "brightness(0) invert(1)" } : {}),
        ...style,
      }}
    />
  );
}
