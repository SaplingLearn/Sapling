"use client";

import { useEffect, useMemo, useState } from "react";
import { CANDIDATES, DEFAULT_SELECTION, type FontCandidate, type FontRole } from "./candidates";
import { genericFor, stackFor } from "./useGoogleFonts";

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

export type NavFontOverride = Record<FontRole, string | null>;

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

  const stackOrNull = (role: FontRole): string | null => {
    if (selection[role] === DEFAULT_SELECTION[role]) return null;
    const candidate = CANDIDATES[role].find((c) => c.family === selection[role]);
    if (!candidate) return null;
    return stackFor(candidate, genericFor(role, candidate.family));
  };

  return {
    heading: stackOrNull("heading"),
    body: stackOrNull("body"),
    label: stackOrNull("label"),
    subtitle: stackOrNull("subtitle"),
  };
}
