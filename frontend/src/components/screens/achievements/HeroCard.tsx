"use client";
import React from "react";
import type { GamificationMe } from "@/lib/types";
import { stageAssetPath } from "@/components/growth/levels";

export function HeroCard({ me }: { me: GamificationMe }) {
  const R = 68;
  const C = 2 * Math.PI * R;
  return (
    <div data-testid="gamification-hero" className="card py-6 px-7.5 flex items-center gap-7.5 mb-4">
      <div className="relative w-33 h-33 shrink-0 flex items-center justify-center">
        <svg width={150} height={150} viewBox="0 0 150 150" className="absolute [transform:rotate(-90deg)]">
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--bg-soft)" strokeWidth={8} />
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--accent)" strokeWidth={8}
                  strokeLinecap="round" strokeDasharray={C}
                  strokeDashoffset={C * (1 - me.level_pct / 100)} />
        </svg>
        <img src={stageAssetPath(me.stage.slug)} alt={me.stage.name}
             width={92} height={92}
             className="absolute rounded-[50%]" />
        <div data-testid="gamification-level" className="absolute -bottom-1 left-1/2 [transform:translateX(-50%)] bg-accent text-accent-fg text-[10.5px] font-semibold py-[3px] px-2.5 rounded-[var(--r-full)] whitespace-nowrap">
          LVL {me.level}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="label-micro">Growth stage · Level {me.level}</div>
        <div className="flex items-baseline gap-3 flex-wrap mt-[3px]">
          <span className="text-4xl font-semibold tracking-[-0.02em]">{me.stage.name}</span>
          <span className="text-base italic text-text-dim">{me.stage.blurb}</span>
        </div>
        <div className="mt-4 max-w-140">
          <div className="flex justify-between items-baseline mb-1.5 gap-2.5">
            <span className="text-sm font-semibold">
              <span data-testid="gamification-total-xp">{me.total_xp}</span> XP total
            </span>
            <span className="text-xs text-text-muted whitespace-nowrap">
              {me.xp_for_level > 0
                ? `${me.xp_into_level} / ${me.xp_for_level} XP → Level ${me.next_level}`
                : "Highest stage reached"}
            </span>
          </div>
          <div className="h-[9px] bg-bg-soft rounded-[var(--r-full)] overflow-hidden">
            <div className="h-full bg-accent rounded-[var(--r-full)]" style={{ width: `${me.level_pct}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
