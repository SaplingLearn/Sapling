import React from "react";

export const SAPLING_WORDMARK_SRC = "/design/sapling/originals/logo-letters.svg";

export const SAPLING_WORDMARK_LIGHT_SRC = "/design/sapling/originals/logo-letters.svg";

const ASPECT = 395.02 / 1294.89;

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
