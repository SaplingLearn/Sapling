"use client";

import { useUser } from "@/context/UserContext";
import { useAchievementUnlockWatcher } from "@/lib/useAchievementUnlockWatcher";

export function AchievementUnlockWatcher() {
  const { userId } = useUser();
  useAchievementUnlockWatcher(userId);
  return null;
}
