"use client";
import React from "react";
import { fetchActivity } from "@/lib/api";
import type { ActivityData } from "@/lib/types";
import { cn } from "@/lib/cn";

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
    <div className="card py-4 px-4.5">
      <div className="label-micro">{label}</div>
      <div data-testid={testId} className="text-2xl font-semibold mt-1">{value}</div>
      {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

const WEEK_CHART_H = 140;
const TREND_CHART_H = 100;

function WeeklyChart({ week, dailyGoalXp }: { week: ActivityData["week"]; dailyGoalXp: number }) {
  const xps = week.map((d) => d.xp);
  const scaleMax = Math.max(...xps, dailyGoalXp) * 1.15 || 1;
  const heights = barHeights(xps, scaleMax, WEEK_CHART_H);
  const goalY = computeGoalY(dailyGoalXp, scaleMax, WEEK_CHART_H);
  const todayIdx = week.length - 1;

  return (
    <div className="card py-4.5 px-5 mb-4">
      <div className="label-micro mb-3.5">This week</div>
      <div className="relative h-35 pt-1">
        <div
          className="absolute left-0 right-0 [border-top:1.5px_dashed_var(--text-muted)]" style={{ top: goalY }}
          aria-hidden
        />
        <div className="absolute inset-0 flex items-end justify-between gap-1.5">
          {week.map((d, i) => {
            const metGoal = d.xp >= dailyGoalXp && dailyGoalXp > 0;
            const isToday = i === todayIdx;
            const bg = isToday ? "var(--accent)" : metGoal ? "var(--brand-forest)" : "var(--bg-soft)";
            return (
              <div key={d.date} className="flex flex-col items-center gap-1.5 flex-1">
                <div
                  title={`${d.day} ${d.date}: ${d.xp} XP`}
                  className="w-7 rounded-[var(--r-xs)_var(--r-xs)_0_0]" style={{ height: heights[i], background: bg }}
                />
              </div>
            );
          })}
        </div>
      </div>
      <div className="flex justify-between gap-1.5 mt-2">
        {week.map((d) => (
          <div key={d.date} className="flex-1 text-center text-xs text-text-muted">
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
    <div className="card py-4.5 px-5">
      <div className="label-micro mb-3.5">Last 8 weeks</div>
      <div className="flex items-end justify-between gap-1.5 h-25">
        {trend.map((t, i) => (
          <div key={`${t.label}-${i}`} className="flex flex-col items-center gap-1.5 flex-1">
            <div
              title={`${t.label}: ${t.xp} XP`}
              className={cn("w-3.5 [border-radius:3px_3px_0_0]", i === trend.length - 1 ? "bg-accent" : "bg-bg-soft")} style={{ height: heights[i] }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between gap-1.5 mt-2">
        {trend.map((t, i) => (
          <div key={`${t.label}-lbl-${i}`} className="flex-1 text-center text-2xs text-text-muted">
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
      <div className="py-15 px-8 text-center text-text-muted text-md">
        Loading activity…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-15 px-8 text-center text-text-muted text-md">
        Couldn&apos;t load activity right now.
      </div>
    );
  }

  const weekAllZero = data.week.every((d) => d.xp === 0);

  return (
    <div className="py-6 px-8">
      <div className="grid grid-cols-[repeat(4,_1fr)] gap-3.5 mb-4">
        <StatTile testId="activity-week-total" label="Week total" value={`${data.tiles.week_total} XP`} />
        <StatTile label="Daily average" value={`${data.tiles.daily_avg} XP`} />
        <StatTile label="Best day" value={`${data.tiles.best_day} XP`} sub={data.tiles.best_day_label || undefined} />
        <StatTile label="Streak" value={`${data.tiles.streak} day${data.tiles.streak === 1 ? "" : "s"}`} />
      </div>

      <WeeklyChart week={data.week} dailyGoalXp={data.daily_goal_xp} />
      {weekAllZero && (
        <div className="text-sm text-text-muted mb-4 -mt-2">
          No XP earned this week yet — study sessions and quizzes will show up here.
        </div>
      )}
      <TrendChart trend={data.trend} />
    </div>
  );
}
