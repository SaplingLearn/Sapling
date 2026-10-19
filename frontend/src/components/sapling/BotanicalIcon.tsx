import React from "react";

/**
 * The approved Pen botanical icons (handoff assets/asset-manifest.json),
 * served byte-for-byte from public/design/sapling. Every one is a single
 * #416207 silhouette, so a CSS mask reproduces the exact authored geometry
 * while the colour follows `currentColor` (hover, active and forced-colours
 * states keep working). `width`/`height` are the authored intrinsic sizes;
 * the mask is `contain`-fitted, so the aspect ratio is never distorted.
 */
export const BOTANICAL_ASSETS = {
  today: { file: "nav-today.svg", width: 22, height: 16.587, penNode: "l2RIf" },
  learn: { file: "nav-learn.svg", width: 22, height: 20.742, penNode: "Q3Qtc5" },
  knowledge: { file: "nav-knowledge.svg", width: 22, height: 22, penNode: "UWjIe" },
  library: { file: "nav-library.svg", width: 22, height: 20.798, penNode: "cPSOV" },
  tutor: { file: "nav-tutor.svg", width: 22, height: 27.677, penNode: "eLW36" },
  calendar: { file: "nav-calendar.svg", width: 22, height: 25.043, penNode: "tD2Nx" },
  paper: { file: "paper.svg", width: 21, height: 24, penNode: "AHtpg" },
  clov: { file: "clov-avatar.svg", width: 29, height: 29, penNode: "J19WJ2" },
} as const;

export type BotanicalIconName = keyof typeof BOTANICAL_ASSETS;

export const SAPLING_ASSET_BASE = "/design/sapling";

export function botanicalIconSrc(name: BotanicalIconName): string {
  return `${SAPLING_ASSET_BASE}/${BOTANICAL_ASSETS[name].file}`;
}

export interface BotanicalIconProps {
  name: BotanicalIconName;
  /** Edge of the square box the icon is fitted into, in px. */
  size?: number;
  /**
   * Omit for decorative use (the default): the parent control carries the
   * accessible name. Give a label only when the icon stands alone.
   */
  label?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function BotanicalIcon({ name, size = 22, label, className, style }: BotanicalIconProps) {
  return (
    <span
      className={["sapling-icon", className].filter(Boolean).join(" ")}
      data-icon={name}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{
        width: size,
        height: size,
        ["--sapling-icon-src" as string]: `url("${botanicalIconSrc(name)}")`,
        ...style,
      }}
    />
  );
}

/** The approved two-tone wordmark (Pen x1GRsP). Kept as an image: its two
 *  authored greens must not be flattened to one colour. */
export function SaplingWordmark({ width = 150, decorative = false, className }: {
  width?: number;
  decorative?: boolean;
  className?: string;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a 2-tone vector; next/image adds nothing for SVG
    <img
      src={`${SAPLING_ASSET_BASE}/sapling-wordmark-approved.svg`}
      alt={decorative ? "" : "Sapling"}
      aria-hidden={decorative || undefined}
      width={width}
      height={Math.round((width * 44.55) / 150)}
      className={["sapling-wordmark", className].filter(Boolean).join(" ")}
      draggable={false}
      decoding="async"
    />
  );
}
