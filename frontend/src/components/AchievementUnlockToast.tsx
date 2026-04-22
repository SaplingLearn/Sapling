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
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        borderLeft: `3px solid ${borderColor}`,
        paddingLeft: 10,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "var(--r-sm)",
          background: "var(--bg-subtle)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          fontSize: 14,
        }}
      >
        {achievement.icon ? (
          achievement.icon.startsWith("http") || achievement.icon.startsWith("/") ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={achievement.icon} alt="" style={{ width: 20, height: 20 }} />
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
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-dim)",
            fontWeight: 500,
            letterSpacing: "0.02em",
          }}
        >
          Achievement unlocked
        </div>
        <div
          style={{
            fontSize: 13,
            color: "var(--text)",
            fontWeight: 500,
          }}
        >
          {achievement.name}
        </div>
      </div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          color: borderColor,
          flexShrink: 0,
        }}
      >
        {achievement.rarity}
      </div>
    </div>
  );
}
