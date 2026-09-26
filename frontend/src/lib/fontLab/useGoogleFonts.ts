"use client";

import { useEffect, useState } from "react";
import { CANDIDATES, type FontCandidate, type FontRole } from "./candidates";

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

/** Sans-shaped label candidates that aren't actually monospaced. */
const LABEL_SANS_FAMILIES = new Set(["Space Grotesk", "Archivo", "Archivo Narrow"]);
/** Subtitle candidates that are upright sans-italics rather than serif-italics. */
const SUBTITLE_SANS_FAMILIES = new Set(["DM Sans", "Karla", "Work Sans"]);

/** The right last-resort keyword for a candidate's stack, given its role. */
export function genericFor(role: FontRole, family: string): "serif" | "sans-serif" | "monospace" {
  if (role === "heading") return "serif";
  if (role === "body") return "sans-serif";
  if (role === "label") return LABEL_SANS_FAMILIES.has(family) ? "sans-serif" : "monospace";
  return SUBTITLE_SANS_FAMILIES.has(family) ? "sans-serif" : "serif";
}

/** CSS `font-family` value for a candidate, with a sane generic fallback. */
export function stackFor(c: FontCandidate, generic: "serif" | "sans-serif" | "monospace"): string {
  return `'${c.family}', ${generic}`;
}
