"use client";

import React from "react";
import type { RarityTier } from "@/lib/types";

interface Props {
  achievement: {
    name: string;
    icon: string | null;
    rarity: RarityTier;
  };
}

const RARITY_VAR: Record<RarityTier, string> = {
  common: "var(--rarity-common)",
  uncommon: "var(--rarity-uncommon)",
  rare: "var(--rarity-rare)",
  epic: "var(--rarity-epic)",
  legendary: "var(--rarity-legendary)",
};

export function AchievementUnlockToast({ achievement }: Props) {
  const borderColor = RARITY_VAR[achievement.rarity] || RARITY_VAR.common;

  return (
    <div
      className="flex items-center gap-2.5"
    >
      <div
        className="w-7 h-7 rounded-sm bg-bg-subtle flex items-center justify-center shrink-0 text-base"
      >
        {achievement.icon ? (
          achievement.icon.startsWith("http") || achievement.icon.startsWith("/") ? (
            <img src={achievement.icon} alt="" className="w-5 h-5" />
          ) : (
            <span>{achievement.icon}</span>
          )
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" strokeWidth="1.5">
            <circle cx="8" cy="8" r="6" />
            <path d="M8 5v3l2 1" />
          </svg>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div
          className="text-xs text-text-dim font-medium tracking-[0.02em]"
        >
          Achievement unlocked
        </div>
        <div
          className="text-md text-text font-medium"
        >
          {achievement.name}
        </div>
      </div>
      <div
        className="flex items-center gap-[5px] text-sm font-semibold text-text shrink-0"
      >
        <span aria-hidden="true" className="w-1.5 h-1.5 rounded-[50%] shrink-0" style={{ background: borderColor }} />
        {achievement.rarity}
      </div>
    </div>
  );
}
