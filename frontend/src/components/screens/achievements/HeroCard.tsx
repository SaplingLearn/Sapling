"use client";
import React from "react";
import type { GamificationMe } from "@/lib/types";
import { stageAssetPath } from "@/components/growth/levels";

export function HeroCard({ me }: { me: GamificationMe }) {
  const R = 68;
  const C = 2 * Math.PI * R;
  return (
    <div className="card" style={{ padding: "24px 30px", display: "flex", alignItems: "center", gap: 30, marginBottom: 16 }}>
      <div style={{ position: "relative", width: 132, height: 132, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width={150} height={150} viewBox="0 0 150 150" style={{ position: "absolute", transform: "rotate(-90deg)" }}>
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--bg-soft)" strokeWidth={8} />
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--accent)" strokeWidth={8}
                  strokeLinecap="round" strokeDasharray={C}
                  strokeDashoffset={C * (1 - me.level_pct / 100)} />
        </svg>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={stageAssetPath(me.stage.slug)} alt={me.stage.name}
             width={92} height={92}
             style={{ position: "absolute", borderRadius: "50%" }} />
        <div style={{ position: "absolute", bottom: -4, left: "50%", transform: "translateX(-50%)",
                      background: "var(--accent)", color: "#fff", fontSize: 10.5, fontWeight: 600,
                      padding: "3px 10px", borderRadius: "var(--r-full)", whiteSpace: "nowrap" }}>
          LVL {me.level}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="label-micro">Growth stage · Level {me.level}</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginTop: 3 }}>
          <span style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em" }}>{me.stage.name}</span>
          <span style={{ fontSize: 14, fontStyle: "italic", color: "var(--text-dim)" }}>{me.stage.blurb}</span>
        </div>
        <div style={{ marginTop: 16, maxWidth: 560 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6, gap: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>{me.total_xp.toLocaleString()} XP total</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
              {me.xp_for_level > 0
                ? `${me.xp_into_level} / ${me.xp_for_level} XP → Level ${me.next_level}`
                : "Highest stage reached"}
            </span>
          </div>
          <div style={{ height: 9, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${me.level_pct}%`, background: "var(--accent)", borderRadius: "var(--r-full)" }} />
          </div>
        </div>
      </div>
    </div>
  );
}
