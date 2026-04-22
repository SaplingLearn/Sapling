"use client";

import React, { useEffect, useRef } from "react";
import { fetchAchievements, IS_LOCAL_MODE } from "./api";
import type { UserAchievement } from "./types";
import { useToast } from "@/components/ToastProvider";
import { AchievementUnlockToast } from "@/components/AchievementUnlockToast";

const POLL_MS = 60_000;

export function useAchievementUnlockWatcher(userId: string) {
  const toast = useToast();
  const seenIds = useRef<Set<string> | null>(null);
  const primed = useRef(false);

  useEffect(() => {
    if (!userId || IS_LOCAL_MODE) return;
    let cancelled = false;

    const check = async () => {
      try {
        const { earned } = await fetchAchievements(userId);
        if (cancelled) return;
        const current = new Set(earned.map((a: UserAchievement) => a.achievement.id));

        if (!primed.current) {
          seenIds.current = current;
          primed.current = true;
          return;
        }

        const prev = seenIds.current ?? new Set<string>();
        const newly = earned.filter(a => !prev.has(a.achievement.id));
        for (const ua of newly) {
          toast.show(React.createElement(AchievementUnlockToast, { achievement: ua.achievement }), {
            duration: 6000,
          });
        }
        seenIds.current = current;
      } catch {
        // silent — watcher shouldn't spam errors
      }
    };

    check();
    const id = setInterval(check, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [userId, toast]);
}
