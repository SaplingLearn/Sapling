"use client";
import React from "react";
import { fetchActivity } from "@/lib/api";
import type { ActivityData } from "@/lib/types";

// Scales `values` into pixel heights for a bar chart of height `chartH`.
// A value of 0 still gets a 4px stub so the bar (and its tooltip target)
// stays visible instead of collapsing to nothing; an all-zero `max` (every
// bucket empty) would otherwise divide by zero, so that case short-circuits
// to stubs for every bar.
export function barHeights(values: number[], max: number, chartH: number): number[] {
  if (!max) return values.map(() => 4);
  return values.map((v) => Math.max(4, Math.round((v / max) * chartH)));
}

// Vertical position (from the top of the chart container) for the dashed
// goal line, on the same `scaleMax` used to size the bars via `barHeights`
// above — a mismatched scale would silently lie about whether a bar's XP
// actually cleared the goal. Deliberately has no `barHeights`-style 4px
// floor: a horizontal line at the very bottom of the chart is still a
// visible line, unlike a bar that would otherwise collapse to nothing.
export function computeGoalY(dailyGoalXp: number, scaleMax: number, chartH: number): number {
  if (!scaleMax) return chartH;
  return chartH - Math.min(chartH, Math.round((dailyGoalXp / scaleMax) * chartH));
}

function StatTile({ label, value, sub, testId }: { label: string; value: React.ReactNode; sub?: string; testId?: string }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div className="label-micro">{label}</div>
      <div data-testid={testId} style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

const WEEK_CHART_H = 140;
const TREND_CHART_H = 100;
const BAR_W = 28;
const TREND_BAR_W = 14;

function WeeklyChart({ week, dailyGoalXp }: { week: ActivityData["week"]; dailyGoalXp: number }) {
  const xps = week.map((d) => d.xp);
  const scaleMax = Math.max(...xps, dailyGoalXp) * 1.15 || 1;
  const heights = barHeights(xps, scaleMax, WEEK_CHART_H);
  const goalY = computeGoalY(dailyGoalXp, scaleMax, WEEK_CHART_H);
  const todayIdx = week.length - 1;

  return (
    <div className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
      <div className="label-micro" style={{ marginBottom: 14 }}>This week</div>
      <div style={{ position: "relative", height: WEEK_CHART_H, paddingTop: 4 }}>
        <div
          style={{
            position: "absolute", left: 0, right: 0, top: goalY,
            borderTop: "1.5px dashed var(--text-muted)",
          }}
          aria-hidden
        />
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 6 }}>
          {week.map((d, i) => {
            const metGoal = d.xp >= dailyGoalXp && dailyGoalXp > 0;
            const isToday = i === todayIdx;
            const bg = isToday ? "var(--accent)" : metGoal ? "var(--brand-forest)" : "var(--bg-soft)";
            return (
              <div key={d.date} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, flex: 1 }}>
                <div
                  title={`${d.day} ${d.date}: ${d.xp} XP`}
                  style={{ width: BAR_W, height: heights[i], background: bg, borderRadius: "var(--r-xs) var(--r-xs) 0 0" }}
                />
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginTop: 8 }}>
        {week.map((d) => (
          <div key={d.date} style={{ flex: 1, textAlign: "center", fontSize: 11, color: "var(--text-muted)" }}>
            {d.day}
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendChart({ trend }: { trend: ActivityData["trend"] }) {
  const xps = trend.map((t) => t.xp);
  const max = Math.max(...xps, 1);
  const heights = barHeights(xps, max, TREND_CHART_H);
  return (
    <div className="card" style={{ padding: "18px 20px" }}>
      <div className="label-micro" style={{ marginBottom: 14 }}>Last 8 weeks</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 6, height: TREND_CHART_H }}>
        {trend.map((t, i) => (
          <div key={`${t.label}-${i}`} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, flex: 1 }}>
            <div
              title={`${t.label}: ${t.xp} XP`}
              style={{
                width: TREND_BAR_W, height: heights[i], borderRadius: "3px 3px 0 0",
                background: i === trend.length - 1 ? "var(--accent)" : "var(--bg-soft)",
              }}
            />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginTop: 8 }}>
        {trend.map((t, i) => (
          <div key={`${t.label}-lbl-${i}`} style={{ flex: 1, textAlign: "center", fontSize: 10, color: "var(--text-muted)" }}>
            {t.label}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ActivityTab({ userId }: { userId: string }) {
  const [data, setData] = React.useState<ActivityData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetchActivity(userId)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((err) => {
        console.error("activity load", err);
        if (!cancelled) setError(true);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [userId]);

  if (loading) {
    return (
      <div style={{ padding: "60px 32px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
        Loading activity…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: "60px 32px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
        Couldn&apos;t load activity right now.
      </div>
    );
  }

  const weekAllZero = data.week.every((d) => d.xp === 0);

  return (
    <div style={{ padding: "24px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 16 }}>
        <StatTile testId="activity-week-total" label="Week total" value={`${data.tiles.week_total} XP`} />
        <StatTile label="Daily average" value={`${data.tiles.daily_avg} XP`} />
        <StatTile label="Best day" value={`${data.tiles.best_day} XP`} sub={data.tiles.best_day_label || undefined} />
        <StatTile label="Streak" value={`${data.tiles.streak} day${data.tiles.streak === 1 ? "" : "s"}`} />
      </div>

      <WeeklyChart week={data.week} dailyGoalXp={data.daily_goal_xp} />
      {weekAllZero && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16, marginTop: -8 }}>
          No XP earned this week yet — study sessions and quizzes will show up here.
        </div>
      )}
      <TrendChart trend={data.trend} />
    </div>
  );
}
