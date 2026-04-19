"use client";
import React from "react";
import { TopBar } from "../TopBar";
import { Pill } from "../Pill";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { fetchAchievements, setFeaturedAchievements } from "@/lib/api";
import type { Achievement as AchType, UserAchievement, RarityTier, AchievementCategory } from "@/lib/types";

const rarityBg: Record<RarityTier, string> = {
  common: "#8a8372",
  uncommon: "#4e873c",
  rare: "#3e6f8a",
  epic: "#7b4b99",
  legendary: "#b4862c",
};

type CatFilter = "all" | AchievementCategory;

const MAX_FEATURED = 5;
const SEEN_KEY = "ach:seen-ids";

function Card({
  a,
  isEarned,
  earnedAt,
  progress,
  featured,
  onToggleFeature,
  canFeature,
}: {
  a: AchType;
  isEarned: boolean;
  earnedAt?: string;
  progress?: { current: number; target: number } | null;
  featured?: boolean;
  onToggleFeature?: () => void;
  canFeature?: boolean;
}) {
  const c = rarityBg[a.rarity];
  const secret = a.is_secret && !isEarned;
  const pct = progress ? Math.min(100, Math.round((progress.current / Math.max(1, progress.target)) * 100)) : null;
  return (
    <div
      className="card"
      style={{
        padding: "var(--pad-lg)",
        position: "relative",
        borderTop: `3px solid ${c}`,
        opacity: isEarned ? 1 : 0.85,
        boxShadow: isEarned ? `0 2px 12px ${c}22, var(--shadow-sm)` : "var(--shadow-sm)",
      }}
    >
      <div style={{ display: "flex", gap: 14 }}>
        <div
          style={{
            width: 52, height: 52, borderRadius: "var(--r-md)",
            background: isEarned ? `${c}22` : "var(--bg-soft)",
            color: c, display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 26, flexShrink: 0,
            filter: isEarned ? "none" : "grayscale(1) opacity(0.5)",
          }}
        >
          {secret ? "?" : a.icon || "★"}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 6 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{secret ? "Secret Achievement" : a.name}</div>
            <span className="chip" style={{ color: c, borderColor: `${c}44`, background: `${c}11` }}>
              {a.rarity}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 3, lineHeight: 1.45 }}>
            {secret ? "Keep exploring to discover this achievement." : a.description}
          </div>
          {isEarned && earnedAt && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Earned {new Date(earnedAt).toLocaleDateString()}
              </div>
              {onToggleFeature && (
                <button
                  onClick={onToggleFeature}
                  disabled={!featured && !canFeature}
                  className="btn btn--xs btn--ghost"
                  title={featured ? "Remove from showcase" : (canFeature ? "Add to showcase" : "Showcase is full (5)")}
                  style={{
                    padding: "2px 7px", fontSize: 10, marginLeft: "auto",
                    color: featured ? "var(--accent)" : "var(--text-dim)",
                    border: `1px solid ${featured ? "var(--accent-border)" : "var(--border)"}`,
                    borderRadius: "var(--r-full)",
                    background: featured ? "var(--accent-soft)" : "transparent",
                  }}
                >
                  {featured ? "★ Featured" : "☆ Feature"}
                </button>
              )}
            </div>
          )}
          {!isEarned && pct !== null && (
            <div style={{ marginTop: 10 }}>
              <div style={{ height: 5, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
                <div style={{ width: "100%", height: "100%", background: c, transformOrigin: "left", transform: `scaleX(${pct / 100})`, transition: "transform var(--dur) var(--ease)" }} />
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4, display: "flex", justifyContent: "space-between" }}>
                <span>{progress!.current} / {progress!.target}</span>
                <span>{pct}%</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function Achievements() {
  const toast = useToast();
  const { userId, userReady } = useUser();
  const [earned, setEarned] = React.useState<UserAchievement[]>([]);
  const [available, setAvailable] = React.useState<AchType[]>([]);
  const [filter, setFilter] = React.useState<CatFilter>("all");
  const [featuredIds, setFeaturedIds] = React.useState<string[]>([]);
  const [dragId, setDragId] = React.useState<string | null>(null);

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

  const cats: CatFilter[] = ["all", "activity", "social", "milestone", "special"];
  const matches = (a: { category: AchievementCategory }) => filter === "all" || a.category === filter;
  const earnedFiltered = earned.filter((e) => matches(e.achievement));
  const availableFiltered = available.filter(matches);
  const earnedById = React.useMemo(() => new Map(earned.map(u => [u.achievement.id, u])), [earned]);

  return (
    <div>
      <TopBar
        breadcrumb="Home / Achievements"
        title="Achievements"
        subtitle={`${earned.length} earned · ${available.length} in progress`}
      />
      <div style={{ padding: "14px 32px", display: "flex", gap: 6, borderBottom: "1px solid var(--border)" }}>
        {cats.map((c) => (
          <Pill key={c} active={filter === c} onClick={() => setFilter(c)}>{c}</Pill>
        ))}
      </div>

      <div style={{ padding: "24px 32px" }}>
        <div className="label-micro" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>Showcase · featured on your profile</span>
          <span style={{ color: "var(--text-muted)" }}>{featuredIds.length} / {MAX_FEATURED}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${MAX_FEATURED}, 1fr)`, gap: 10, marginBottom: 30 }}>
          {featuredIds.map((id) => {
            const ua = earnedById.get(id);
            if (!ua) return null;
            const c = rarityBg[ua.achievement.rarity];
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

        <div className="label-micro" style={{ marginBottom: 12 }}>Earned · {earnedFiltered.length}</div>
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
          gap: 14, marginBottom: 30,
        }}>
          {earnedFiltered.map((ua) => (
            <Card
              key={ua.achievement.id}
              a={ua.achievement}
              isEarned
              earnedAt={ua.earned_at}
              featured={featuredIds.includes(ua.achievement.id)}
              canFeature={featuredIds.length < MAX_FEATURED}
              onToggleFeature={() => toggleFeature(ua.achievement.id)}
            />
          ))}
        </div>

        <div className="label-micro" style={{ marginBottom: 12 }}>Locked · {availableFiltered.length}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {availableFiltered.map((a) => (
            <Card key={a.id} a={a} isEarned={false} progress={a.progress ?? null} />
          ))}
        </div>
      </div>
    </div>
  );
}
