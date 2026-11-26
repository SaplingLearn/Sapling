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
import { humanizeError } from "@/lib/errorMessage";
import { sentenceCase } from "@/lib/sentenceCase";
import { cn } from "@/lib/cn";

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
    <div role="tablist" className="flex gap-1 py-0 px-8 border-b border-b-border">
      {TABS.map((t) => (
        <button
          key={t.value}
          data-testid={`achievements-tab-${t.value}`}
          role="tab"
          aria-selected={tab === t.value}
          onClick={() => onChange(t.value)}
          className={cn("py-2.5 px-4 text-md -mb-px", tab === t.value ? "font-semibold" : "font-medium", tab === t.value ? "text-text" : "text-text-dim", tab === t.value ? "border-b-2 border-b-accent" : "border-b-2 border-b-transparent")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="card py-4 px-4.5">
      <div className="label-micro">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function GoalRing({ value, max, size = 40 }: { value: number; max: number; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0 [transform:rotate(-90deg)]">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-soft)" strokeWidth={5} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth={5}
              strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} />
    </svg>
  );
}

function StatRow({ me }: { me: GamificationMe }) {
  return (
    <div className="grid grid-cols-[repeat(3,_1fr)] gap-3.5 mb-7.5">
      <StatTile
        label="Streak"
        value={`${me.streak} day${me.streak === 1 ? "" : "s"}`}
        sub={`longest ${me.longest_streak}`}
      />
      <div className="card py-4 px-4.5 flex items-center gap-3">
        <GoalRing value={me.today_xp} max={me.daily_goal_xp} />
        <div className="min-w-0">
          <div className="label-micro">Daily goal</div>
          <div className="text-lg font-semibold mt-0.5">{me.today_xp} / {me.daily_goal_xp} XP</div>
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

  // Showcase edit state (#767). `featuredRef` is the list the user is looking
  // at, readable synchronously so edits never compute from a stale closure;
  // `savedRef` is the last list the server confirmed, which a failed save
  // rolls back to. `editSeq` counts edits (a load that started before one
  // must not overwrite it) and `savesInFlight` keeps a window-focus reload
  // from clobbering an edit still being saved.
  const featuredRef = React.useRef<string[]>([]);
  const savedRef = React.useRef<string[]>([]);
  const editSeq = React.useRef(0);
  const savedSeq = React.useRef(0);
  const savesInFlight = React.useRef(0);
  const showFeatured = React.useCallback((ids: string[]) => {
    featuredRef.current = ids;
    setFeaturedIds(ids);
  }, []);

  /** The ids already announced, from localStorage. Never throws.
   *
   * This was a bare `JSON.parse(... || "[]")` with no guard, in a callback
   * that runs on every Achievements load. Two ways it took the screen down:
   * malformed JSON threw from `JSON.parse`, and well-formed JSON that is not
   * an array (`{}`, `5`) threw from `new Set(...)` because it is not
   * iterable. Either way the throw escaped into render and the screen went
   * to the error boundary — and it STAYED there on reload, because the value
   * that caused it is persisted. A value we cannot read is treated as "none
   * seen yet", which at worst re-announces an achievement once. */
  const readSeenIds = React.useCallback((): Set<string> => {
    try {
      const parsed: unknown = JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]");
      if (!Array.isArray(parsed)) return new Set();
      return new Set(parsed.filter((id): id is string => typeof id === "string"));
    } catch {
      return new Set();
    }
  }, []);

  const detectUnlocks = React.useCallback((next: UserAchievement[]) => {
    if (typeof window === "undefined") return;
    const seen = readSeenIds();
    const fresh = next.filter(u => !seen.has(u.achievement.id));
    for (const u of fresh) {
      if (seen.size > 0) toast.success(`Achievement unlocked: ${u.achievement.name}`);
      seen.add(u.achievement.id);
    }
    try {
      window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
    } catch {
      // Storage full or blocked (Safari private mode): the toast already
      // fired, and failing to remember that is not worth a crash.
    }
  }, [toast, readSeenIds]);

  const load = React.useCallback(async () => {
    if (!userId) return;
    const seqAtStart = editSeq.current;
    try {
      const d = await fetchAchievements(userId);
      const e = d.earned || [];
      setEarned(e);
      setAvailable(d.available || []);
      // Only adopt the server's showcase when no edit happened since this
      // load started and none is still saving — otherwise the focus refetch
      // would overwrite the user's unsaved reorder/removal.
      if (editSeq.current === seqAtStart && savesInFlight.current === 0) {
        const serverFeatured = e.filter(u => u.is_featured).map(u => u.achievement.id);
        savedRef.current = serverFeatured;
        showFeatured(serverFeatured);
      }
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
  }, [userId, detectUnlocks, showFeatured]);

  React.useEffect(() => {
    if (userReady && userId) load();
  }, [userReady, userId, load]);

  // Refetch on window focus to pick up unlocks from other tabs/sessions.
  React.useEffect(() => {
    const onFocus = () => { if (userId) load(); };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [userId, load]);

  // Show the edit, then save it. Deliberately NOT inside a setState updater:
  // React may run an updater twice (StrictMode does), which sent the save
  // request — and its failure toast — twice.
  const commitFeatured = async (next: string[]) => {
    if (!userId) return;
    const seq = ++editSeq.current;
    showFeatured(next);
    savesInFlight.current += 1;
    try {
      await setFeaturedAchievements(userId, next);
      // Each save sends the whole list, so the newest confirmed one is what
      // the server holds; an older save confirming late must not replace it.
      if (seq > savedSeq.current) {
        savedSeq.current = seq;
        savedRef.current = next;
      }
    } catch (err) {
      // Roll back only if no newer edit superseded this one — that edit's
      // own save decides the final state.
      if (seq === editSeq.current) {
        showFeatured(savedRef.current);
        toast.error(humanizeError(err, "Couldn't save your showcase. Try again."));
      }
    } finally {
      savesInFlight.current -= 1;
    }
  };

  const toggleFeature = (id: string) => {
    const prev = featuredRef.current;
    const isIn = prev.includes(id);
    if (!isIn && prev.length >= MAX_FEATURED) {
      toast.warn(`Showcase is full (max ${MAX_FEATURED}). Remove one first.`);
      return;
    }
    void commitFeatured(isIn ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const reorder = (sourceId: string, targetId: string) => {
    const prev = featuredRef.current;
    const from = prev.indexOf(sourceId);
    const to = prev.indexOf(targetId);
    if (from < 0 || to < 0 || from === to) return;
    const next = [...prev];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    void commitFeatured(next);
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
          <div className="py-3.5 px-8 border-b border-b-border">
            <FilterPills
              options={filterOptions}
              value={filter}
              onChange={setFilter}
            />
          </div>

          {loading && <AchievementsSkeleton />}
          {!loading && <div className="py-6 px-8">
            {me && <HeroCard me={me} />}
            {me && <StatRow me={me} />}

            <div className="label-micro mb-3 flex justify-between items-center">
              <span>Showcase · featured on your profile</span>
              <span className="text-text-muted">{featuredIds.length} / {MAX_FEATURED}</span>
            </div>
            <div className="grid gap-2.5 mb-7.5" style={{ gridTemplateColumns: `repeat(${MAX_FEATURED}, 1fr)` }}>
              {featuredIds.map((id, idx) => {
                const ua = earnedById.get(id);
                if (!ua) return null;
                const c = rarityVar(ua.achievement.rarity);
                // Drag events fire for pointers only, so without these the
                // showcase order is unreachable by keyboard or touch-assistive
                // tech. `reorder` moves the source to the target's index, so
                // handing it the neighbour is exactly a one-slot move.
                const move = (delta: -1 | 1) => {
                  const neighbour = featuredIds[idx + delta];
                  if (neighbour) reorder(id, neighbour);
                };
                return (
                  <div
                    key={id}
                    draggable
                    onDragStart={() => setDragId(id)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => { if (dragId && dragId !== id) reorder(dragId, id); setDragId(null); }}
                    onDragEnd={() => setDragId(null)}
                    className={cn("card", "p-3 text-center cursor-grab relative", dragId === id ? "opacity-50" : "opacity-100")}
                    style={{ borderTop: `3px solid ${c}` }}
                  >
                    <button
                      data-testid={`achievements-showcase-remove-${id}`}
                      onClick={() => toggleFeature(id)}
                      aria-label="Remove from showcase"
                      className="absolute top-1 right-1 w-4.5 h-4.5 rounded-[50%] bg-bg-soft text-text-muted flex items-center justify-center text-2xs"
                    >
                      <Icon name="x" size={10} />
                    </button>
                    <div className="text-3xl mb-1">{ua.achievement.icon || "★"}</div>
                    <div className="text-xs font-semibold">{ua.achievement.name}</div>
                    <div className="text-sm text-text-muted mt-0.5">
                      {sentenceCase(ua.achievement.rarity)}
                    </div>
                    <div className="flex justify-center gap-1 mt-1.5">
                      <button
                        data-testid={`achievements-showcase-left-${id}`}
                        className="btn btn--sm btn--ghost py-0 px-1.5 text-xs leading-[18px]"
                        aria-label={`Move ${ua.achievement.name} earlier in the showcase`}
                        disabled={idx === 0}
                        onClick={() => move(-1)}
                      >
                        ←
                      </button>
                      <button
                        data-testid={`achievements-showcase-right-${id}`}
                        className="btn btn--sm btn--ghost py-0 px-1.5 text-xs leading-[18px]"
                        aria-label={`Move ${ua.achievement.name} later in the showcase`}
                        disabled={idx === featuredIds.length - 1}
                        onClick={() => move(1)}
                      >
                        →
                      </button>
                    </div>
                  </div>
                );
              })}
              {Array.from({ length: Math.max(0, MAX_FEATURED - featuredIds.length) }).map((_, i) => (
                <div
                  key={`slot-${i}`}
                  className="border-[1.5px] border-dashed border-border-strong rounded-lg p-3 min-h-20 text-center text-text-muted text-xs flex items-center justify-center"
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
