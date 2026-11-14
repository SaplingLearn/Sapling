"use client";

/**
 * The signed-in account's onboarding draft: loaded once per account, saved on
 * every change (without its Terms and Privacy answers: draft.ts forStorage),
 * discarded once the profile is saved.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { clearOnboardingDraft, writeOnboardingDraft } from "@/lib/onboardingDraft";
import { EMPTY_DRAFT, forStorage, loadDraft, type Draft } from "./draft";

export interface DraftState {
  /** The signed-in account's draft; empty until it is loaded (`hydrated`). */
  draft: Draft;
  /** Whether the draft in state is the signed-in account's own: false until
   * it is loaded, and again after a switch of account until the new one's is. */
  hydrated: boolean;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  patch: (p: Partial<Draft>) => void;
  /** Stop saving and remove the stored draft (the profile is saved). */
  discard: () => void;
}

/**
 * `onHydrate` runs once the account's draft is in state, with whether a
 * draft past the first screen was resumed (the intro is skipped for one).
 */
export function useOnboardingDraft(
  userId: string,
  accountName: string,
  onHydrate: (resumed: boolean) => void,
): DraftState {
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  // Whose draft is in state: its tag. In the render between a switch of
  // account and the re-hydrate it is still the previous account's, so until
  // it matches the signed-in user the draft reads as empty and is not saved
  // (and Onboarding won't finish it): one account's answers never go out
  // under another's.
  const [hydratedFor, setHydratedFor] = useState<string | null>(null);
  const hydrated = !!userId && hydratedFor === userId;
  const discarded = useRef(false);
  // Read when an account hydrates, not tracked: a name refreshed from
  // /api/auth/me must not reload the draft or replay the intro.
  const latest = useRef({ accountName, onHydrate });
  useEffect(() => {
    latest.current = { accountName, onHydrate };
  });

  useEffect(() => {
    if (!userId) return;
    const saved = loadDraft(userId);
    // The Google account's name fills both fields; the student can change either.
    const [googleFirst = "", ...rest] = latest.current.accountName.trim().split(/\s+/);
    const googleLast = rest.join(" ");
    discarded.current = false;
    const base = saved ?? EMPTY_DRAFT;
    // Syncing from localStorage (an external store) into state is this
    // effect's whole job; it runs once per account.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft({ ...base, name: base.name || googleFirst, lastName: base.lastName || googleLast });
    setHydratedFor(userId);
    latest.current.onHydrate(!!saved && saved.screen > 0);
  }, [userId]);

  useEffect(() => {
    if (!hydrated || discarded.current) return;
    writeOnboardingDraft(userId, forStorage(draft));
  }, [draft, hydrated, userId]);

  const patch = useCallback((p: Partial<Draft>) => setDraft(prev => ({ ...prev, ...p })), []);

  const discard = useCallback(() => {
    discarded.current = true;
    if (userId) clearOnboardingDraft(userId);
  }, [userId]);

  return { draft: hydrated ? draft : EMPTY_DRAFT, hydrated, setDraft, patch, discard };
}
