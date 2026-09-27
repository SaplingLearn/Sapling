"use client";

import { useEffect, useMemo, useState } from "react";
import { CANDIDATES, DEFAULT_SELECTION, type FontCandidate, type FontRole } from "./candidates";
import { stackFor } from "./useGoogleFonts";

/**
 * Lets the real dashboard sidebar preview whatever `/font-lab` last had
 * selected, so a pick can be judged in the actual product instead of only
 * the lab's replica. Reads one localStorage key that only the lab ever
 * writes, so this is inert — no fetch, no behavior change — for every
 * visitor who has never opened it.
 *
 * Only a role whose stored pick differs from the shipped default fetches
 * anything: self-hosted faces resolve to a Next-generated family name, not
 * their human name (see `app/layout.tsx`), so a bare `'DM Sans'` stack would
 * silently fall back to system sans unless the real face is loaded here —
 * exactly the failure mode that file's `next/font/google` ban exists to
 * prevent. This hook is the one place in the shipped app allowed to load a
 * Google Fonts stylesheet at runtime, and only when a hand-picked override
 * is present.
 */

export const FONT_LAB_STORAGE_KEY = "sapling_font_lab_selection_v1";
export const FONT_LAB_EVENT = "sapling:font-lab-change";

export type FontLabSelection = Record<FontRole, string>;

const ROLE_KEYS: FontRole[] = ["heading", "body", "label", "subtitle"];

export function readFontLabSelection(): FontLabSelection | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(FONT_LAB_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (ROLE_KEYS.every((role) => typeof parsed?.[role] === "string")) return parsed;
    return null;
  } catch {
    return null;
  }
}

/**
 * Everything a role needs to actually LOOK like the candidate that was
 * picked — not just its family name. A section-label candidate picked for
 * its weight (Big Shoulders Display at 900, say) rendered exactly as thin
 * as the shipped default until this carried `fontWeight` too: the rail's
 * CSS never set a weight on that row, so every override silently inherited
 * the browser's normal/400 regardless of which face was chosen. Subtitle's
 * italic candidates had the same bug with `fontStyle`.
 */
export type RoleStyle = { fontFamily: string; fontWeight: number; fontStyle: "normal" | "italic" };

export type NavFontOverride = Record<FontRole, RoleStyle | null>;

export function useNavFontOverride(): NavFontOverride | null {
  const [selection, setSelection] = useState<FontLabSelection | null>(() => readFontLabSelection());

  useEffect(() => {
    function sync() {
      setSelection(readFontLabSelection());
    }
    window.addEventListener("storage", sync);
    window.addEventListener(FONT_LAB_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(FONT_LAB_EVENT, sync);
    };
  }, []);

  const overridden = useMemo(() => {
    if (!selection) return [];
    return ROLE_KEYS.filter((role) => selection[role] !== DEFAULT_SELECTION[role])
      .map((role) => CANDIDATES[role].find((c) => c.family === selection[role]))
      .filter((c): c is FontCandidate => Boolean(c));
  }, [selection]);

  useEffect(() => {
    if (overridden.length === 0) return;
    const params = overridden.map((c) => `family=${encodeURIComponent(c.family)}:${c.axes}`).join("&");
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?${params}&display=swap`;
    document.head.appendChild(link);
    return () => {
      document.head.removeChild(link);
    };
  }, [overridden]);

  if (!selection) return null;

  const styleOrNull = (role: FontRole): RoleStyle | null => {
    if (selection[role] === DEFAULT_SELECTION[role]) return null;
    const candidate = CANDIDATES[role].find((c) => c.family === selection[role]);
    if (!candidate) return null;
    return {
      fontFamily: stackFor(candidate),
      fontWeight: candidate.previewWeight,
      fontStyle: candidate.italic ? "italic" : "normal",
    };
  };

  return {
    heading: styleOrNull("heading"),
    body: styleOrNull("body"),
    label: styleOrNull("label"),
    subtitle: styleOrNull("subtitle"),
  };
}
