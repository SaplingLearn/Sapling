"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { FilterPills } from "@/components/ui";
import { Icon } from "../Icon";
import { AchievementsSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { fetchAchievements, fetchGamificationMe, setFeaturedAchievements } from "@/lib/api";
import type { Achievement as AchType, AchievementCategory, UserAchievement, RarityTier, GamificationMe } from "@/lib/types";
import { HeroCard } from "./achievements/HeroCard";
import { BadgeGrid, CAT_META, CAT_ORDER, type CategoryFilter } from "./achievements/BadgeGrid";
import { BadgeModal } from "./achievements/BadgeModal";
import { LeaderboardTab } from "./achievements/LeaderboardTab";
import { ActivityTab } from "./achievements/ActivityTab";

// Rarity colors come only from the canonical --rarity-* tokens (globals.css);
// rarity text itself stays neutral (colored text fails 4.5:1 on several tiers).
const rarityVar = (r: RarityTier) => `var(--rarity-${r}, var(--border))`;

const MAX_FEATURED = 5;
const SEEN_KEY = "ach:seen-ids";

type Tab = "achievements" | "leaderboard" | "activity";
const TABS: { value: Tab; label: string }[] = [
  { value: "achievements", label: "Achievements" },
  { value: "leaderboard", label: "Leaderboard" },
  { value: "activity", label: "Activity" },
];

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <div role="tablist" style={{ display: "flex", gap: 4, padding: "0 32px", borderBottom: "1px solid var(--border)" }}>
      {TABS.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={tab === t.value}
          onClick={() => onChange(t.value)}
          style={{
            padding: "10px 16px", fontSize: 13, fontWeight: tab === t.value ? 600 : 500,
            color: tab === t.value ? "var(--text)" : "var(--text-dim)",
            borderBottom: `2px solid ${tab === t.value ? "var(--accent)" : "transparent"}`,
            marginBottom: -1,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div className="label-micro">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function GoalRing({ value, max, size = 40 }: { value: number; max: number; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0, transform: "rotate(-90deg)" }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-soft)" strokeWidth={5} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={5}
              strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
    </svg>
  );
}

function StatRow({ me }: { me: GamificationMe }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 30 }}>
      <StatTile
        label="Streak"
        value={`${me.streak} day${me.streak === 1 ? "" : "s"}`}
        sub={`longest ${me.longest_streak}`}
      />
      <div className="card" style={{ padding: "16px 18px", display: "flex", alignItems: "center", gap: 12 }}>
        <GoalRing value={me.today_xp} max={me.daily_goal_xp} />
        <div style={{ minWidth: 0 }}>
          <div className="label-micro">Daily goal</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginTop: 2 }}>{me.today_xp} / {me.daily_goal_xp} XP</div>
        </div>
      </div>
      <StatTile label="Badges" value={`${me.earned_count} / ${me.total_count}`} sub="earned" />
    </div>
  );
}

export function Achievements() {
  const toast = useToast();
  const { userId, userReady } = useUser();
  const [tab, setTab] = React.useState<Tab>("achievements");
  const [earned, setEarned] = React.useState<UserAchievement[]>([]);
  const [available, setAvailable] = React.useState<AchType[]>([]);
  const [filter, setFilter] = React.useState<CategoryFilter>("all");
  const [me, setMe] = React.useState<GamificationMe | null>(null);
  const [featuredIds, setFeaturedIds] = React.useState<string[]>([]);
  const [dragId, setDragId] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [openAchievement, setOpenAchievement] = React.useState<AchType | null>(null);

  const detectUnlocks = React.useCallback((next: UserAchievement[]) => {
    if (typeof window === "undefined") return;
    const seen = new Set<string>(JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]"));
    const fresh = next.filter(u => !seen.has(u.achievement.id));
    for (const u of fresh) {
      if (seen.size > 0) toast.success(`Achievement unlocked: ${u.achievement.name}`);
      seen.add(u.achievement.id);
    }
    window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
  }, [toast]);

  const load = React.useCallback(async () => {
    if (!userId) return;
    try {
      const d = await fetchAchievements(userId);
      const e = d.earned || [];
      setEarned(e);
      setAvailable(d.available || []);
      setFeaturedIds(e.filter(u => u.is_featured).map(u => u.achievement.id));
      detectUnlocks(e);
    } catch (err) {
      console.error("achievements load", err);
    } finally {
      setLoading(false);
    }
    // Fetched independently of the achievements list above: a failure here
    // (or a slow response) must not block the earned/locked grids from
    // loading, and must not blank the page — the hero + stat row simply
    // don't render while `me` is null.
    try {
      const m = await fetchGamificationMe(userId);
      setMe(m);
    } catch (err) {
      console.error("gamification me load", err);
    }
  }, [userId, detectUnlocks]);

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  // Refetch on window focus to pick up unlocks from other tabs/sessions.
  React.useEffect(() => {
    const onFocus = () => { if (userId) load(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [userId, load]);

  const persistFeatured = async (ids: string[]) => {
    if (!userId) return;
    try {
      await setFeaturedAchievements(userId, ids);
    } catch (err) {
      toast.error(`Couldn't save showcase: ${String(err)}`);
    }
  };

  const toggleFeature = (id: string) => {
    setFeaturedIds(prev => {
      const isIn = prev.includes(id);
      const next = isIn ? prev.filter(x => x !== id) : (prev.length < MAX_FEATURED ? [...prev, id] : prev);
      if (!isIn && prev.length >= MAX_FEATURED) {
        toast.warn(`Showcase is full (max ${MAX_FEATURED}). Remove one first.`);
        return prev;
      }
      persistFeatured(next);
      return next;
    });
  };

  const reorder = (sourceId: string, targetId: string) => {
    setFeaturedIds(prev => {
      const from = prev.indexOf(sourceId);
      const to = prev.indexOf(targetId);
      if (from < 0 || to < 0 || from === to) return prev;
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      persistFeatured(next);
      return next;
    });
  };

  const earnedById = React.useMemo(() => new Map(earned.map(u => [u.achievement.id, u])), [earned]);
  // Union of earned + not-yet-earned achievements for the grid — the API
  // returns these as two disjoint lists (never both containing the same id).
  const allAchievements = React.useMemo(
    () => [...earned.map(u => u.achievement), ...available],
    [earned, available],
  );
  // Catalog totals per category, for the FilterPills counts — "All" shows
  // the full catalog total, each category pill shows its own total.
  const catalogCountByCategory = React.useMemo(() => {
    const m = new Map<AchievementCategory, number>();
    for (const a of allAchievements) m.set(a.category, (m.get(a.category) ?? 0) + 1);
    return m;
  }, [allAchievements]);
  const filterOptions: { value: CategoryFilter; label: string }[] = [
    { value: "all", label: `All · ${allAchievements.length}` },
    ...CAT_ORDER.map((c) => ({
      value: c as CategoryFilter,
      label: `${CAT_META[c].label} · ${catalogCountByCategory.get(c) ?? 0}`,
    })),
  ];

  return (
    <div>
      <TopBar
        title="Achievements"
        subtitle={`${earned.length} earned · ${available.length} in progress`}
      />
      <TabBar tab={tab} onChange={setTab} />

      {tab === "achievements" && (
        <>
          <div style={{ padding: "14px 32px", borderBottom: "1px solid var(--border)" }}>
            <FilterPills
              options={filterOptions}
              value={filter}
              onChange={setFilter}
            />
          </div>

          {loading && <AchievementsSkeleton />}
          {!loading && <div style={{ padding: "24px 32px" }}>
            {me && <HeroCard me={me} />}
            {me && <StatRow me={me} />}

            <div className="label-micro" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Showcase · featured on your profile</span>
              <span style={{ color: "var(--text-muted)" }}>{featuredIds.length} / {MAX_FEATURED}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${MAX_FEATURED}, 1fr)`, gap: 10, marginBottom: 30 }}>
              {featuredIds.map((id) => {
                const ua = earnedById.get(id);
                if (!ua) return null;
                const c = rarityVar(ua.achievement.rarity);
                return (
                  <div
                    key={id}
                    draggable
                    onDragStart={() => setDragId(id)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => { if (dragId && dragId !== id) reorder(dragId, id); setDragId(null); }}
                    onDragEnd={() => setDragId(null)}
                    className="card"
                    style={{
                      padding: 12, textAlign: "center",
                      borderTop: `3px solid ${c}`,
                      opacity: dragId === id ? 0.5 : 1,
                      cursor: "grab",
                      position: "relative",
                    }}
                  >
                    <button
                      onClick={() => toggleFeature(id)}
                      aria-label="Remove from showcase"
                      style={{
                        position: "absolute", top: 4, right: 4,
                        width: 18, height: 18, borderRadius: "50%",
                        background: "var(--bg-soft)", color: "var(--text-muted)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 10,
                      }}
                    >
                      <Icon name="x" size={10} />
                    </button>
                    <div style={{ fontSize: 26, marginBottom: 4 }}>{ua.achievement.icon || "★"}</div>
                    <div style={{ fontSize: 11, fontWeight: 600 }}>{ua.achievement.name}</div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 2 }}>
                      {ua.achievement.rarity}
                    </div>
                  </div>
                );
              })}
              {Array.from({ length: Math.max(0, MAX_FEATURED - featuredIds.length) }).map((_, i) => (
                <div
                  key={`slot-${i}`}
                  style={{
                    border: "1.5px dashed var(--border-strong)",
                    borderRadius: "var(--r-lg)", padding: 12, minHeight: 80,
                    textAlign: "center", color: "var(--text-muted)", fontSize: 11,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  + empty slot
                </div>
              ))}
            </div>

            <BadgeGrid achievements={allAchievements} earnedById={earnedById} onOpen={setOpenAchievement} category={filter} />
          </div>}
        </>
      )}

      {tab === "leaderboard" && userId && <LeaderboardTab userId={userId} />}
      {tab === "activity" && userId && <ActivityTab userId={userId} />}

      {openAchievement && (
        <BadgeModal
          achievement={openAchievement}
          earned={earnedById.get(openAchievement.id)}
          onClose={() => setOpenAchievement(null)}
        />
      )}
    </div>
  );
}
