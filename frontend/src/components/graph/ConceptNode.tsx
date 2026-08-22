"use client";

/**
 * ConceptNode — one concept, drawn the way the tree draws it (#537).
 *
 * A NEW component, not a refactor of `KnowledgeGraph2D`'s `<g>`: that mark is
 * welded to the d3 tick fast-path, five Playwright testids and two overlay
 * rings the quiz doesn't want. What the two share is the arithmetic —
 * everything numeric here comes from `lib/graph/nodeStyle`, so a retune of the
 * tree moves this mark too.
 *
 * GEOMETRY. The mark is authored once in *reference units* — a 30×30 box whose
 * half-width is `NODE_REF_RADIUS`, the same scale `radiusFor()` returns — and
 * the `size` prop only sets the SVG's CSS width. That is what makes a 15px dot
 * and a 26px node "the same mark at two sizes": the mastery radius is scaled
 * into `size` rather than recomputed per call site. A fully-mastered concept
 * (r 20) would overflow the reference box, so the body radius is clamped;
 * the glow is allowed to spill (the class sets `overflow: visible`), because a
 * blurred halo clipped to a square edge reads as a box, not a glow.
 */

import React from "react";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import {
  GLOW,
  NODE_STROKE_OPACITY,
  opacityFor,
  radiusFor,
  shadeFor,
  tierFor,
  truncateLabel,
} from "@/lib/graph/nodeStyle";

export type ConceptNodeVariant =
  | { kind: "dot" }
  | { kind: "node" }
  | { kind: "growth"; before: number; after: number };

/** Half the reference box. `radiusFor()`'s outputs are in these units. */
export const NODE_REF_RADIUS = 15;
/** The reference viewBox is square at twice the reference radius. */
export const NODE_REF_BOX = NODE_REF_RADIUS * 2;
/** Reference-unit gap between the mark and its caption — the tree's `r + 13`. */
export const LABEL_GAP = 13;
/** Reference-unit band added below the box when a caption is drawn. */
const LABEL_BAND = 18;
/** Stroke weights, in reference units. The tree does not scale these. */
const STROKE_WIDTH = 1.5;
const ROOT_STROKE_WIDTH = 2.5;
/** The grown mark carries a slightly heavier ring — it's the point of the screen. */
const GROWTH_STROKE_WIDTH = 2;
/** The "before" ring on a growth mark. */
const BEFORE_RING = { dash: "4 4", opacity: 0.5 } as const;

/**
 * The drawn radius of a mark: `radiusFor()` in reference units, clamped so a
 * fully-mastered concept (r 20) can't overflow the reference box, then scaled.
 * Callers that need to place a caption relative to the mark use this too, so
 * the two can't disagree.
 */
export function markRadius(mastery: number, isRoot = false, scale = 1): number {
  return Math.min(radiusFor(mastery, isRoot), NODE_REF_RADIUS - STROKE_WIDTH / 2) * scale;
}

/**
 * True while the growth mark should be animating. Returns `[grown, animating]`:
 * `grown` is the render-time state (false only for the first frame of a real
 * animation), `animating` says whether a transition is expected at all.
 *
 * With `prefers-reduced-motion` or `animate={false}` this starts — and stays —
 * grown, so the very first paint is the identical end state and no transition
 * ever runs. The growth path uses `requestAnimationFrame` rather than a bare
 * effect because the browser needs one paint at the start value for the
 * transition to have anything to interpolate from.
 */
export function useGrowth(variant: ConceptNodeVariant, animate: boolean): [boolean, boolean] {
  const prefersReducedMotion = usePrefersReducedMotion();
  const animating = variant.kind === "growth" && animate && !prefersReducedMotion;
  const [grown, setGrown] = React.useState(!animating);

  React.useEffect(() => {
    if (!animating) {
      setGrown(true);
      return;
    }
    setGrown(false);
    const raf = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(raf);
  }, [animating, variant.kind]);

  return [grown, animating];
}

export interface ConceptMarkProps {
  /** Centre, in the host SVG's own units. */
  cx: number;
  cy: number;
  /** Multiplier applied to every reference radius. 1 inside `<ConceptNode>`. */
  scale: number;
  mastery: number;
  tier: string;
  /** The course base colour — shading is applied here, not by the caller. */
  courseColor: string;
  nodeId: string;
  isRoot?: boolean;
  variant: ConceptNodeVariant;
  /** `url(#…)` target for the blur filter. Omit for a flat mark. */
  glowFilterId?: string;
  /** Growth only: false renders the "before" size so a transition has somewhere to start. */
  grown?: boolean;
}

/**
 * The mark itself, as bare SVG children so both `<ConceptNode>` (its own
 * `<svg>`) and `<ConceptNeighbourhood>` (one shared canvas) draw the identical
 * shape. Callers own the `<defs>` that `glowFilterId` points at.
 */
export function ConceptMark({
  cx,
  cy,
  scale,
  mastery,
  tier,
  courseColor,
  nodeId,
  isRoot = false,
  variant,
  glowFilterId,
  grown = true,
}: ConceptMarkProps) {
  // Subject roots are never shaded — the family reads as one colour (the tree
  // does the same at KnowledgeGraph2D's `courseColor`).
  const color = isRoot ? courseColor : shadeFor(courseColor, nodeId);

  const growth = variant.kind === "growth" ? variant : null;
  const effectiveMastery = growth ? growth.after : mastery;
  // R-12: the submit response carries `mastery_after` but no tier, so this is
  // the one place the quiz derives a tier from a score.
  const effectiveTier = growth ? tierFor(growth.after) : tier;

  const rBody = markRadius(effectiveMastery, isRoot, scale);
  const rBefore = growth ? markRadius(growth.before, false, scale) : 0;
  const opacity = isRoot ? 1 : opacityFor(effectiveTier);
  const strokeWidth = growth ? GROWTH_STROKE_WIDTH : isRoot ? ROOT_STROKE_WIDTH : STROKE_WIDTH;

  // Pre-animation, the body sits at the "before" size. Scaling the drawn
  // circle (rather than swapping `r`) keeps the transition on a property every
  // browser composites, and the ratio rides a custom property so the rule
  // itself stays in globals.css.
  const growFrom = growth && !grown && rBody > 0 ? rBefore / rBody : 1;

  return (
    <>
      {glowFilterId && (
        <circle
          className="concept-node__glow"
          cx={cx}
          cy={cy}
          r={rBody + GLOW.pad * scale}
          fill={color}
          opacity={GLOW.opacity}
          filter={`url(#${glowFilterId})`}
        />
      )}
      {growth && (
        <circle
          className="concept-node__before"
          cx={cx}
          cy={cy}
          r={rBefore}
          fill="none"
          stroke={color}
          strokeWidth={STROKE_WIDTH}
          strokeDasharray={BEFORE_RING.dash}
          opacity={BEFORE_RING.opacity}
        />
      )}
      <circle
        className={growth ? "concept-node__body concept-node__body--growth" : "concept-node__body"}
        cx={cx}
        cy={cy}
        r={rBody}
        fill={color}
        opacity={opacity}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeOpacity={NODE_STROKE_OPACITY}
        style={
          growth ? ({ "--concept-grow": growFrom.toFixed(4) } as React.CSSProperties) : undefined
        }
      />
    </>
  );
}

export interface ConceptNodeProps {
  /** Rendered diameter in CSS px. The mastery radius is scaled into it. */
  size: number;
  /** 0..1. Ignored by the `growth` variant in favour of before/after. */
  mastery: number;
  /** The server's `mastery_tier` string — never recompute it from a score (R-12). */
  tier: string;
  /** Course base colour. A `var(--…)` value passes through `shadeFor` unshaded. */
  courseColor: string;
  /** The shade seed. MUST be the graph node id, not the concept name. */
  nodeId: string;
  /**
   * Optional caption under the mark, truncated like the tree's. The box grows
   * to fit it vertically, but the text can be wider than the mark and spills
   * sideways (the SVG is `overflow: visible` for the glow) — exactly as the
   * tree's own labels do inside the graph canvas. Marks laid out in a tight
   * row should label themselves in HTML instead.
   */
  label?: string;
  variant?: ConceptNodeVariant;
  isRoot?: boolean;
  /** Growth only. `prefers-reduced-motion` overrides a `true` here. */
  animate?: boolean;
  /** Accessible name. Without one the mark is decorative and hidden. */
  title?: string;
  testid?: string;
}

export function ConceptNode({
  size,
  mastery,
  tier,
  courseColor,
  nodeId,
  label,
  variant = { kind: "node" },
  isRoot = false,
  animate = true,
  title,
  testid,
}: ConceptNodeProps) {
  const filterId = `concept-node-glow-${React.useId()}`;
  const [grown] = useGrowth(variant, animate);

  const hasGlow = variant.kind !== "dot";
  const truncated = label ? truncateLabel(label) : null;
  const boxHeight = truncated ? NODE_REF_BOX + LABEL_BAND : NODE_REF_BOX;
  const centre = NODE_REF_RADIUS;
  const rBody = markRadius(variant.kind === "growth" ? variant.after : mastery, isRoot);

  return (
    <svg
      className="concept-node"
      width={size}
      height={(size * boxHeight) / NODE_REF_BOX}
      viewBox={`0 0 ${NODE_REF_BOX} ${boxHeight}`}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      data-testid={testid}
    >
      {hasGlow && (
        <defs>
          <filter id={filterId}>
            <feGaussianBlur stdDeviation={GLOW.blur} />
          </filter>
        </defs>
      )}
      <ConceptMark
        cx={centre}
        cy={centre}
        scale={1}
        mastery={mastery}
        tier={tier}
        courseColor={courseColor}
        nodeId={nodeId}
        isRoot={isRoot}
        variant={variant}
        glowFilterId={hasGlow ? filterId : undefined}
        grown={grown}
      />
      {truncated && (
        <text className="concept-node__label" x={centre} y={centre + rBody + LABEL_GAP} textAnchor="middle">
          {truncated}
        </text>
      )}
    </svg>
  );
}
