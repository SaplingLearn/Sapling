"use client";
import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../Icon";
import { useOverlayBehaviour } from "@/components/Dialog";
import { BadgeArt } from "@/components/growth/BadgeArt";
import type { Achievement, UserAchievement } from "@/lib/types";
import { CAT_META } from "./BadgeGrid";
import { sentenceCase } from "@/lib/sentenceCase";

// 14 leaf-burst spans fanned evenly around the badge — a small flourish that
// only plays when the badge is earned. Each span keeps a fixed rotation as
// its own base transform (set inline below) so the shared `sap-burst`
// keyframe (globals.css) only has to handle scale + fade; that keyframe is
// swallowed by the app-wide `prefers-reduced-motion: reduce` reset already
// in globals.css (the universal `*, *::before, *::after` rule), so no
// separate media query is needed here.
const BURST_COUNT = 14;
const BURST_SPANS = Array.from({ length: BURST_COUNT }, (_, i) => ({
  rot: (360 / BURST_COUNT) * i,
  delay: (i % 7) * 0.05,
}));

export function BadgeModal({
  achievement, earned, onClose,
}: {
  achievement: Achievement;
  earned?: UserAchievement;
  onClose: () => void;
}) {
  // The app's one modal engine (Dialog's): portal readiness, scroll lock,
  // focus in and back out, Escape and the Tab trap. This panel keeps its own
  // chrome, so it takes the behaviour rather than <Dialog>.
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open: true, onClose });

  if (!mounted) return null;

  const isEarned = !!earned;
  const secret = achievement.is_secret && !isEarned;
  const progress = achievement.progress ?? null;
  const pct = progress
    ? Math.min(100, Math.round((progress.current / Math.max(1, progress.target)) * 100))
    : null;

  return createPortal(
    <div
      onClick={onClose}
      onKeyDown={onKeyDown}
      className="fixed inset-0 bg-[rgba(25,_37,_11,0.45)] z-200 grid place-items-center p-5"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={secret ? "Secret achievement" : achievement.name}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="card slide-up w-[min(380px,_100%)] pt-7.5 px-6.5 pb-6.5 text-center relative outline-none"
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="btn btn--ghost btn--sm absolute top-2.5 right-2.5"
        >
          <Icon name="x" size={14} />
        </button>

        <div className="relative w-32.5 h-32.5 mt-0 mx-auto mb-4.5">
          {isEarned && (
            <div aria-hidden className="absolute inset-0 pointer-events-none">
              {BURST_SPANS.map((b, i) => (
                <span
                  key={i}
                  className="absolute top-1/2 left-1/2" style={{ transform: `rotate(${b.rot}deg) translate(0, -68px)` }}
                >
                  <span
                    className="inline-block text-md" style={{ animation: `sap-burst 900ms ease-out ${b.delay}s both` }}
                  >
                    🍃
                  </span>
                </span>
              ))}
            </div>
          )}
          <BadgeArt slug={secret ? "secret" : achievement.slug} rarity={achievement.rarity}
                    locked={!isEarned} iconUrl={achievement.icon_url} emoji={achievement.icon} size={130} />
        </div>

        <div className="text-[20px] font-semibold">{secret ? "???" : achievement.name}</div>
        <div className="flex justify-center mt-2">
          <span className="chip">{sentenceCase(achievement.rarity)} · {CAT_META[achievement.category].label}</span>
        </div>
        <div className="text-md text-text-dim mt-3.5 leading-[1.5]">
          {secret ? "A hidden achievement. Keep exploring to discover it." : achievement.description}
        </div>

        {isEarned && earned && (
          <div className="mt-4.5 text-[12.5px] text-accent font-medium">
            Earned {new Date(earned.earned_at).toLocaleDateString()} · +{achievement.xp_reward} XP
          </div>
        )}
        {!isEarned && pct !== null && (
          <div className="mt-4.5">
            <div className="h-1.5 bg-bg-soft rounded-[var(--r-full)] overflow-hidden">
              <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
            </div>
            <div className="flex justify-between text-xs text-text-muted mt-1.5">
              <span>{progress!.current} / {progress!.target}</span><span>{pct}%</span>
            </div>
          </div>
        )}
        {!isEarned && pct === null && (
          <div className="mt-4.5 text-md text-text-muted">
            Not yet unlocked · +{achievement.xp_reward} XP
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
