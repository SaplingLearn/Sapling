"use client";

/**
 * Which Connect options onboarding leaves out. An account whose feature is
 * hidden by its nav flag (#620) can't be connected or used: with
 * `hide_calendar` on, /api/calendar/* answers 404 (so the consent hand-off
 * would end on one), and with `hide_grades` on the Gradebook sends its
 * visitors to the dashboard. The app's FlagsProvider loads flags only inside
 * the shell, so onboarding reads them itself, once per account, falling back
 * like the provider to this browser's last-known copy.
 *
 * Until the answer is in — and when there is none at all — the flagged
 * options are left out: connecting later from the Calendar or Gradebook page
 * beats a hand-off that ends on a 404.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchFlags, type FlagMap } from "@/lib/flags";
import { readLastKnownFlags } from "@/context/FlagsContext";
import { CONNECTIONS, type ConnChoices, type ConnKey } from "./flow";

export function hiddenConnections(flags: FlagMap | null): Set<ConnKey> {
  return new Set(
    CONNECTIONS.filter(c => c.flag && (flags === null || flags[c.flag] === "on")).map(c => c.key),
  );
}

/** The choices without the options that are left out. */
export function visibleChoices(conn: ConnChoices, hidden: Set<ConnKey>): ConnChoices {
  return Object.fromEntries(Object.entries(conn).filter(([key]) => !hidden.has(key as ConnKey)));
}

interface Answer {
  userId: string;
  flags: FlagMap | null;
}

export function useHiddenConnections(userId: string): {
  /** For rendering. */
  hidden: Set<ConnKey>;
  /** The answer as of now, render or not: what the hand-off after the save uses. */
  current: () => Set<ConnKey>;
} {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const latest = useRef<Answer | null>(null);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    fetchFlags()
      .catch(() => readLastKnownFlags(userId))
      .then(flags => {
        if (cancelled) return;
        latest.current = { userId, flags };
        setAnswer(latest.current);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const flags = answer && answer.userId === userId ? answer.flags : null;
  const hidden = useMemo(() => hiddenConnections(flags), [flags]);
  const current = useCallback(
    () => hiddenConnections(latest.current && latest.current.userId === userId ? latest.current.flags : null),
    [userId],
  );
  return { hidden, current };
}
