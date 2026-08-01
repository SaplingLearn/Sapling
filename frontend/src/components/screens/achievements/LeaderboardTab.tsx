"use client";
import React from "react";
import { Toggle } from "@/components/ui";
import { Avatar } from "@/components/Avatar";
import { fetchLeaderboard } from "@/lib/api";
import type { LeaderboardRow } from "@/lib/types";

type Scope = "everyone" | "friends" | "school";
const SCOPES: { value: Scope; label: string }[] = [
  { value: "everyone", label: "Everyone" },
  { value: "friends", label: "Friends" },
  { value: "school", label: "School" },
];

function formatResetTimer(resetsAt: string): string {
  const ms = new Date(resetsAt).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return "resets soon";
  const totalMinutes = Math.floor(ms / 60000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  if (days > 0) return `resets in ${days}d ${hours}h`;
  const minutes = totalMinutes % 60;
  if (hours > 0) return `resets in ${hours}h ${minutes}m`;
  return `resets in ${Math.max(1, minutes)}m`;
}

const PODIUM_HEIGHT: Record<1 | 2 | 3, number> = { 1: 108, 2: 84, 3: 64 };

function PodiumSpot({ row, place }: { row: LeaderboardRow; place: 1 | 2 | 3 }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
      <Avatar name={row.name} size={place === 1 ? 56 : 46} />
      <div style={{ fontSize: 12.5, fontWeight: 600, textAlign: "center", maxWidth: 110, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {row.name}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{row.week_xp.toLocaleString()} XP</div>
      <div
        style={{
          width: "100%", height: PODIUM_HEIGHT[place],
          background: "var(--bg-soft)", borderRadius: "var(--r-md) var(--r-md) 0 0",
          display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: 8,
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-dim)" }}>#{place}</span>
      </div>
    </div>
  );
}

export type PodiumSpot = { row: LeaderboardRow; place: 1 | 2 | 3 };

// Podium order is visual left-to-right (2nd, 1st, 3rd), not rank order —
// only returns the places that actually have a row, so a 1- or 2-row board
// doesn't index past the end (a naive `rows[1], rows[0], rows[2]` would) and
// stays visually centered rather than leaving a phantom gap where a missing
// place would sit.
export function buildPodiumSpots(rows: LeaderboardRow[]): PodiumSpot[] {
  const [first, second, third] = rows;
  const spots: PodiumSpot[] = [];
  if (second) spots.push({ row: second, place: 2 });
  if (first) spots.push({ row: first, place: 1 });
  if (third) spots.push({ row: third, place: 3 });
  return spots;
}

function Podium({ rows }: { rows: LeaderboardRow[] }) {
  const spots = buildPodiumSpots(rows);
  if (!spots.length) return null;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 16, padding: "8px 24px 0", marginBottom: 8 }}>
      {spots.map((s) => <PodiumSpot key={s.row.user_id} row={s.row} place={s.place} />)}
    </div>
  );
}

function RankRow({ row }: { row: LeaderboardRow }) {
  return (
    <div
      data-testid={row.is_you ? "leaderboard-row-you" : undefined}
      style={{
        display: "flex", alignItems: "center", gap: 12, padding: "10px 16px",
        borderRadius: "var(--r-md)",
        background: row.is_you ? "var(--accent-soft)" : "transparent",
      }}
    >
      <div style={{ width: 24, textAlign: "center", fontSize: 12.5, fontWeight: 600, color: "var(--text-dim)" }}>
        {row.rank}
      </div>
      <Avatar name={row.name} size={30} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {row.name}
        </span>
        {row.is_you && <span className="chip chip--accent">YOU</span>}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
        {row.stage} · Lvl {row.level}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--text-muted)", whiteSpace: "nowrap", width: 64, textAlign: "right" }}>
        {row.streak} day{row.streak === 1 ? "" : "s"}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, width: 76, textAlign: "right" }}>
        {row.week_xp.toLocaleString()} XP
      </div>
    </div>
  );
}

export function LeaderboardTab({ userId }: { userId: string }) {
  const [scope, setScope] = React.useState<Scope>("everyone");
  const [rows, setRows] = React.useState<LeaderboardRow[]>([]);
  const [you, setYou] = React.useState<LeaderboardRow | null>(null);
  const [resetsAt, setResetsAt] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(false);
  const requestRef = React.useRef(0);

  React.useEffect(() => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(false);
    fetchLeaderboard(userId, scope)
      .then((d) => {
        // A slower fetch for a scope the user has since switched away from
        // must not clobber what's on screen — only the most recent request
        // for this effect run is allowed to commit state.
        if (requestRef.current !== requestId) return;
        setRows(d.rows || []);
        setYou(d.you);
        setResetsAt(d.resets_at);
      })
      .catch((err) => {
        console.error("leaderboard load", err);
        if (requestRef.current === requestId) setError(true);
      })
      .finally(() => {
        if (requestRef.current === requestId) setLoading(false);
      });
  }, [userId, scope]);

  const podiumRows = rows.slice(0, 3);
  // The backend guarantees the viewer appears in `rows`; if `you` is
  // missing anyway (private profile, race, etc.) fall back to scanning
  // `rows` for the flagged entry rather than assuming it can't happen.
  const viewerRow = you ?? rows.find((r) => r.is_you) ?? null;

  return (
    <div style={{ padding: "24px 32px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18, gap: 12, flexWrap: "wrap" }}>
        <Toggle options={SCOPES} value={scope} onChange={setScope} />
        {resetsAt && (
          <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
            Weekly board {formatResetTimer(resetsAt)}
          </div>
        )}
      </div>

      {loading && (
        <div style={{ padding: "60px 32px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          Loading leaderboard…
        </div>
      )}

      {!loading && error && (
        <div style={{ padding: "60px 32px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          Couldn&apos;t load the leaderboard right now.
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div style={{ padding: "60px 32px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          No XP earned in this group yet this week.
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          <Podium rows={podiumRows} />
          <div className="card" style={{ padding: 8 }}>
            {rows.map((row) => <RankRow key={row.user_id} row={row} />)}
          </div>
          {viewerRow && !rows.some((r) => r.user_id === viewerRow.user_id) && (
            // Defensive only: today the viewer's row is always inside `rows`,
            // but if that ever changes, still surface their standing rather
            // than silently omitting it. Checked by user_id, not rank — rank
            // contiguity is an implementation detail of the current
            // unpaginated backend, not something the LeaderboardRow type
            // guarantees (xp_events already grew pagination once, #Task 8).
            <div className="card" style={{ padding: 8, marginTop: 10 }}>
              <RankRow row={viewerRow} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
