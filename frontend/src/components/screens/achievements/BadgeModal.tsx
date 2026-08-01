"use client";
import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../Icon";
import { useScrollLock } from "@/lib/useScrollLock";
import { BadgeArt } from "@/components/growth/BadgeArt";
import type { Achievement, UserAchievement } from "@/lib/types";
import { CAT_META } from "./BadgeGrid";

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
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  useScrollLock(true);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

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
      style={{
        position: "fixed", inset: 0, background: "rgba(19,38,16,0.45)",
        zIndex: 200, display: "grid", placeItems: "center", padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card slide-up"
        style={{ width: "min(380px, 100%)", padding: "30px 26px 26px", textAlign: "center", position: "relative" }}
      >
        <button
          onClick={onClose}
          aria-label="Close"
          className="btn btn--ghost btn--sm"
          style={{ position: "absolute", top: 10, right: 10 }}
        >
          <Icon name="x" size={14} />
        </button>

        <div style={{ position: "relative", width: 130, height: 130, margin: "0 auto 18px" }}>
          {isEarned && (
            <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              {BURST_SPANS.map((b, i) => (
                <span
                  key={i}
                  style={{
                    position: "absolute", top: "50%", left: "50%",
                    transform: `rotate(${b.rot}deg) translate(0, -68px)`,
                  }}
                >
                  <span
                    style={{
                      display: "inline-block", fontSize: 13,
                      animation: `sap-burst 900ms ease-out ${b.delay}s both`,
                    }}
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

        <div style={{ fontSize: 20, fontWeight: 600 }}>{secret ? "???" : achievement.name}</div>
        <div style={{ display: "flex", justifyContent: "center", marginTop: 8 }}>
          <span className="chip">{achievement.rarity} · {CAT_META[achievement.category].label}</span>
        </div>
        <div style={{ fontSize: 13, color: "var(--text-dim)", marginTop: 14, lineHeight: 1.5 }}>
          {secret ? "A hidden achievement. Keep exploring to discover it." : achievement.description}
        </div>

        {isEarned && earned && (
          <div style={{ marginTop: 18, fontSize: 12.5, color: "var(--accent)", fontWeight: 500 }}>
            Earned {new Date(earned.earned_at).toLocaleDateString()} · +{achievement.xp_reward} XP
          </div>
        )}
        {!isEarned && pct !== null && (
          <div style={{ marginTop: 18 }}>
            <div style={{ height: 6, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${pct}%`, background: "var(--accent)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
              <span>{progress!.current} / {progress!.target}</span><span>{pct}%</span>
            </div>
          </div>
        )}
        {!isEarned && pct === null && (
          <div style={{ marginTop: 18, fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Not yet unlocked · +{achievement.xp_reward} XP
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
