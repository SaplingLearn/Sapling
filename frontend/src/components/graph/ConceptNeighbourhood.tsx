"use client";

/**
 * ConceptNeighbourhood — a concept and up to three of its neighbours (#537).
 *
 * A still fragment of the tree, not a second renderer: no simulation, no
 * interaction, fixed positions. `siblingsFor` (lib/graph/neighbourhood) picks
 * and orders the neighbours; this component only lays them out, and every
 * radius/colour/opacity comes from the same `ConceptMark` the tree's
 * arithmetic feeds.
 *
 * LAYOUT. The three sibling slots are the design's own — top-left, top-right,
 * bottom-left — expressed as fractions of the canvas.
 *
 * There are TWO compositions, not one, because the design has two. The small
 * canvases (home 320×204, concept dialog 300×200) nudge the centre 8px right
 * of true centre, balancing the two left-hand slots against the single right
 * one. The wide results canvas (640×212) has room to spare and is drawn
 * centred, with its siblings pushed outward; forcing the small canvases'
 * fractions onto it left the top-left slot 19px adrift. `compact` and `wide`
 * reproduce the design's own three canvases to the pixel, and the default is
 * picked from `width`, so a caller passing the documented presets gets the
 * right one without knowing this exists.
 *
 * The top-right slot sits on the canvas edge, so it never gets a caption — it
 * would clip. That matches the design, which drops that label in every preset.
 */

import React from "react";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { GLOW, edgeWidthFor, truncateLabel } from "@/lib/graph/nodeStyle";
import {
  ConceptMark,
  LABEL_GAP,
  markRadius,
  useGrowth,
  type ConceptNodeVariant,
} from "./ConceptNode";

export type NeighbourhoodComposition = "compact" | "wide";

/**
 * The two arrangements, each as (x, y) fractions of the canvas plus the
 * centre's px nudge. Slot order is `siblingsFor`'s: strongest neighbour first.
 *
 * `compact` is the average of the design's two small canvases (it lands within
 * ~6px on both); `wide` is the results canvas read off directly — centre
 * (320, 106) and slots (96, 34) / (628, 48) / (86, 208) at 640×212, which
 * these fractions reproduce to under a pixel.
 */
const COMPOSITIONS: Record<
  NeighbourhoodComposition,
  { centreOffsetX: number; slots: readonly (readonly [number, number])[] }
> = {
  compact: {
    centreOffsetX: 8,
    slots: [
      [0.12, 0.14], // top-left
      [0.975, 0.18], // top-right — on the edge, so never captioned
      [0.15, 0.96], // bottom-left
    ],
  },
  wide: {
    centreOffsetX: 0,
    slots: [
      [0.15, 0.16],
      [0.98125, 0.22642],
      [0.134375, 0.98113],
    ],
  },
};

/** At or above this width the canvas is drawn as the results set piece. */
const WIDE_CANVAS_MIN_WIDTH = 480;

/** Edge opacity — the tree's resting value for the `organism` variant. */
const EDGE_OPACITY = 0.2;

export interface ConceptNeighbourhoodProps {
  centre: { id: string; name: string; mastery: number; tier: string };
  /** Up to 3, already picked and ordered by `siblingsFor`. */
  siblings: NeighbourNode[];
  /** Course base colour; shading happens per node inside the mark. */
  courseColor: string;
  width: number;
  height: number;
  /** Multiplier on the reference radii. The presets use 2 (dialog/home) or 2.5 (results). */
  scale: number;
  centreVariant?: ConceptNodeVariant;
  showLabels?: boolean;
  /** Required: the whole fragment is one image to a screen reader. */
  ariaLabel: string;
  /** Growth only. `prefers-reduced-motion` overrides a `true` here. */
  animate?: boolean;
  /**
   * Which of the design's two arrangements to draw. Defaults from `width`
   * (>= 480 → `wide`), so the three documented presets need never pass it.
   */
  composition?: NeighbourhoodComposition;
  testid?: string;
}

export function ConceptNeighbourhood({
  centre,
  siblings,
  courseColor,
  width,
  height,
  scale,
  centreVariant = { kind: "node" },
  showLabels = true,
  ariaLabel,
  animate = true,
  composition = width >= WIDE_CANVAS_MIN_WIDTH ? "wide" : "compact",
  testid,
}: ConceptNeighbourhoodProps) {
  const filterId = `concept-neighbourhood-glow-${React.useId()}`;
  const [grown] = useGrowth(centreVariant, animate);

  const { centreOffsetX, slots } = COMPOSITIONS[composition];
  const cx = width / 2 + centreOffsetX;
  const cy = height / 2;

  const placed = siblings.slice(0, slots.length).map((sibling, i) => ({
    sibling,
    x: slots[i][0] * width,
    y: slots[i][1] * height,
    // Only the two left-hand slots are captioned (see the header note).
    captioned: showLabels && i !== 1,
  }));

  /** Caption baseline: under the mark, flipped above it when that would fall
   *  off the canvas — which is exactly the bottom-left slot's situation. */
  const captionY = (y: number, r: number) => {
    const below = y + r + LABEL_GAP;
    return below <= height - 2 ? below : y - r - LABEL_GAP / 2;
  };

  return (
    <svg
      className="concept-neighbourhood"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel}
      data-testid={testid}
    >
      <defs>
        <filter id={filterId}>
          <feGaussianBlur stdDeviation={GLOW.blur * scale} />
        </filter>
      </defs>

      {placed.map(({ sibling, x, y }) => (
        <line
          key={`edge-${sibling.id}`}
          className="concept-neighbourhood__edge"
          x1={cx}
          y1={cy}
          x2={x}
          y2={y}
          strokeOpacity={EDGE_OPACITY}
          strokeWidth={edgeWidthFor(sibling.strength)}
          strokeLinecap="round"
        />
      ))}

      {placed.map(({ sibling, x, y, captioned }) => (
        <React.Fragment key={sibling.id}>
          <ConceptMark
            cx={x}
            cy={y}
            scale={scale}
            mastery={sibling.mastery}
            tier={sibling.tier}
            courseColor={courseColor}
            nodeId={sibling.id}
            variant={{ kind: "dot" }}
          />
          {captioned && (
            <text
              className="concept-neighbourhood__label"
              x={x}
              y={captionY(y, markRadius(sibling.mastery, false, scale))}
              textAnchor="middle"
            >
              {truncateLabel(sibling.name)}
            </text>
          )}
        </React.Fragment>
      ))}

      <ConceptMark
        cx={cx}
        cy={cy}
        scale={scale}
        mastery={centre.mastery}
        tier={centre.tier}
        courseColor={courseColor}
        nodeId={centre.id}
        variant={centreVariant}
        glowFilterId={filterId}
        grown={grown}
      />
      {showLabels && (
        <text
          className="concept-neighbourhood__label"
          x={cx}
          y={captionY(
            cy,
            markRadius(
              centreVariant.kind === "growth" ? centreVariant.after : centre.mastery,
              false,
              scale,
            ),
          )}
          textAnchor="middle"
        >
          {truncateLabel(centre.name)}
        </text>
      )}
    </svg>
  );
}
