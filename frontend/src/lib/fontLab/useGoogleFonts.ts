"use client";

import { useEffect, useState } from "react";
import { CANDIDATES, type FontCandidate } from "./candidates";

/**
 * This tool only. Every other route self-hosts its four faces (see
 * `app/layout.tsx`'s reasoning on why `next/font/google` is banned in the
 * product) so a build never silently swaps a real face for Times New Roman.
 * The Font Lab is a design-exploration surface, never shipped to a real
 * user's dashboard, and needs ~50 candidate faces on request — self-hosting
 * that set isn't worth it. A failed request here just leaves a swatch on its
 * fallback, which is the correct failure mode for a tool whose whole job is
 * "try a font and see".
 */

const loadedFamilies = new Set<string>();

function familyParam(c: FontCandidate): string {
  return `family=${encodeURIComponent(c.family)}:${c.axes}`;
}

function buildHref(candidates: FontCandidate[]): string {
  const params = candidates.map(familyParam).join("&");
  return `https://fonts.googleapis.com/css2?${params}&display=swap`;
}

function allLoaded(allCandidates: FontCandidate[]): boolean {
  return allCandidates.every((c) => loadedFamilies.has(c.family + c.axes));
}

/**
 * Loads every candidate face for the given roles in one stylesheet request
 * (Google Fonts accepts repeated `family=` params on a single css2 URL), then
 * swaps it in for a superset link whenever a not-yet-loaded family is asked
 * for later. Keeps a module-level cache so re-mounting the lab (e.g. fast
 * refresh) doesn't refetch.
 */
export function useGoogleFonts(allCandidates: FontCandidate[]) {
  // Lazy initializer, not an effect: if a previous mount already loaded every
  // face this render needs, the first paint can already say so instead of
  // starting `false` and immediately re-rendering to `true`.
  const [ready, setReady] = useState(() => allLoaded(allCandidates));

  useEffect(() => {
    if (allLoaded(allCandidates)) return;
    const missing = allCandidates.filter((c) => !loadedFamilies.has(c.family + c.axes));
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = buildHref(missing);
    link.onload = () => {
      missing.forEach((c) => loadedFamilies.add(c.family + c.axes));
      setReady(true);
    };
    link.onerror = () => {
      // Fonts just fall back — see module note above.
      setReady(true);
    };
    document.head.appendChild(link);
    return () => {
      // Leave the stylesheet in place; other roles' pickers may still need it.
    };
  }, [allCandidates]);

  return ready;
}

/** Flattened, de-duplicated (by family+axes) list of every candidate, across every role. */
export function allFontCandidates(): FontCandidate[] {
  const seen = new Map<string, FontCandidate>();
  (Object.values(CANDIDATES) as FontCandidate[][]).forEach((list) =>
    list.forEach((c) => seen.set(c.family + c.axes, c))
  );
  return Array.from(seen.values());
}

/**
 * CSS `font-family` value for a candidate. The fallback comes from the
 * candidate's own declared shape (`generic`), not a per-role assumption —
 * the label role in particular mixes real monospace faces with at least one
 * deliberate non-mono wild card, so "label roles fall back to monospace"
 * would be wrong for that entry.
 */
export function stackFor(c: FontCandidate): string {
  return `'${c.family}', ${c.generic}`;
}
