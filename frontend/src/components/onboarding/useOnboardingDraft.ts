"use client";

/**
 * The signed-in account's onboarding draft: loaded once per account, saved on
 * every change, discarded once the profile is saved.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { clearOnboardingDraft, writeOnboardingDraft } from "@/lib/onboardingDraft";
import { EMPTY_DRAFT, loadDraft, type Draft } from "./draft";

export interface DraftState {
  draft: Draft;
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
  // Whose draft is in state. Saving only when it matches the signed-in user
  // keeps one account's answers from being written under another's key in
  // the render between a user switch and the re-hydrate.
  const [hydratedFor, setHydratedFor] = useState<string | null>(null);
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
    const googleFirst = latest.current.accountName.trim().split(/\s+/)[0] || "";
    discarded.current = false;
    // Syncing from localStorage (an external store) into state is this
    // effect's whole job; it runs once per account.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(saved ? { ...saved, name: saved.name || googleFirst } : { ...EMPTY_DRAFT, name: googleFirst });
    setHydratedFor(userId);
    latest.current.onHydrate(!!saved && saved.screen > 0);
  }, [userId]);

  useEffect(() => {
    if (!hydratedFor || hydratedFor !== userId || discarded.current) return;
    writeOnboardingDraft(hydratedFor, draft);
  }, [draft, hydratedFor, userId]);

  const patch = useCallback((p: Partial<Draft>) => setDraft(prev => ({ ...prev, ...p })), []);

  const discard = useCallback(() => {
    discarded.current = true;
    if (userId) clearOnboardingDraft(userId);
  }, [userId]);

  return { draft, setDraft, patch, discard };
}
