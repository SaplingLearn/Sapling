"use client";
import React from "react";
import { BadgeArt } from "@/components/growth/BadgeArt";
import type { Achievement, AchievementCategory, UserAchievement } from "@/lib/types";

const CAT_ORDER: AchievementCategory[] = ["activity", "social", "milestone", "special"];

// Category copy, verbatim from the design's CAT_META.
export const CAT_META: Record<AchievementCategory, { label: string; blurb: string }> = {
  activity:  { label: "Activity",  blurb: "Show up, study, and keep the streak alive." },
  social:    { label: "Social",    blurb: "Learning grows faster in good company." },
  milestone: { label: "Milestone", blurb: "The long arc of mastery, one concept at a time." },
  special:   { label: "Special",   blurb: "Rare feats, seasonal moments, and the occasional secret." },
};

export function BadgeGrid({
  achievements, earnedById, onOpen,
}: {
  achievements: Achievement[];
  earnedById: Map<string, UserAchievement>;
  onOpen: (a: Achievement) => void;
}) {
  return (
    <>
      {CAT_ORDER.map((cat) => {
        const list = achievements.filter((a) => a.category === cat);
        if (!list.length) return null;
        const earnedCount = list.filter((a) => earnedById.has(a.id)).length;
        // Earned badges float to the top of their section.
        const ordered = [...list].sort(
          (a, b) => Number(earnedById.has(b.id)) - Number(earnedById.has(a.id))
            || a.sort_order - b.sort_order,
        );
        return (
          <section key={cat} style={{ marginBottom: 38 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>{CAT_META[cat].label}</h2>
              <span className="chip">{earnedCount} / {list.length}</span>
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 16, maxWidth: 640 }}>
              {CAT_META[cat].blurb}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(268px, 1fr))", gap: 14 }}>
              {ordered.map((a) => {
                const ua = earnedById.get(a.id);
                const earned = !!ua;
                const secret = a.is_secret && !earned;
                const pct = a.progress
                  ? Math.min(100, Math.round((a.progress.current / Math.max(1, a.progress.target)) * 100))
                  : null;
                return (
                  <button
                    key={a.id}
                    onClick={() => onOpen(a)}
                    className="card"
                    style={{ textAlign: "left", padding: 18, display: "flex", gap: 15,
                             alignItems: "flex-start", cursor: "pointer" }}
                  >
                    <div style={{ width: 80, height: 80, flexShrink: 0 }}>
                      <BadgeArt slug={secret ? "secret" : a.slug} rarity={a.rarity}
                                locked={!earned} iconUrl={a.icon_url} emoji={a.icon} size={80} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between",
                                    alignItems: "baseline", gap: 6 }}>
                        <div style={{ fontWeight: 600, fontSize: 14.5 }}>
                          {secret ? "???" : a.name}
                        </div>
                        <span className="chip">{a.rarity}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 5, lineHeight: 1.45 }}>
                        {secret ? "A hidden achievement. Keep exploring to discover it." : a.description}
                      </div>
                      {earned && (
                        <div style={{ marginTop: 10, fontSize: 11, color: "var(--accent)", fontWeight: 500 }}>
                          Earned {new Date(ua.earned_at).toLocaleDateString()} · +{a.xp_reward} XP
                        </div>
                      )}
                      {!earned && pct !== null && (
                        <div style={{ marginTop: 11 }}>
                          <div style={{ height: 5, background: "var(--bg-soft)",
                                        borderRadius: "var(--r-full)", overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${pct}%`, background: "var(--accent)" }} />
                          </div>
                          <div style={{ display: "flex", justifyContent: "space-between",
                                        fontSize: 10, color: "var(--text-muted)", marginTop: 5 }}>
                            <span>{a.progress!.current} / {a.progress!.target}</span><span>{pct}%</span>
                          </div>
                        </div>
                      )}
                      {!earned && pct === null && (
                        <div style={{ marginTop: 10, fontSize: 10, color: "var(--text-muted)",
                                      textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Locked · +{a.xp_reward} XP
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
}
