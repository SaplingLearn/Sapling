"use client";
import React from "react";
import { Toggle } from "@/components/ui";
import { Avatar } from "@/components/Avatar";
import { fetchLeaderboard } from "@/lib/api";
import type { LeaderboardRow } from "@/lib/types";
import { cn } from "@/lib/cn";

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
    <div className="flex flex-col items-center gap-2 flex-1 min-w-0">
      <Avatar name={row.name} size={place === 1 ? 56 : 46} />
      <div className="text-[12.5px] font-semibold text-center max-w-27.5 overflow-hidden text-ellipsis whitespace-nowrap">
        {row.name}
      </div>
      <div className="text-xs text-text-muted">{row.week_xp.toLocaleString()} XP</div>
      <div
        className="w-full bg-bg-soft rounded-[var(--r-md)_var(--r-md)_0_0] flex items-start justify-center pt-2" style={{ height: PODIUM_HEIGHT[place] }}
      >
        <span className="text-[15px] font-bold text-text-dim">#{place}</span>
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
    <div className="flex items-end gap-4 pt-2 px-6 pb-0 mb-2">
      {spots.map((s) => <PodiumSpot key={s.row.user_id} row={s.row} place={s.place} />)}
    </div>
  );
}

function RankRow({ row }: { row: LeaderboardRow }) {
  return (
    <div
      data-testid={row.is_you ? "leaderboard-row-you" : undefined}
      className={cn("flex items-center gap-3 py-2.5 px-4 rounded-md", row.is_you ? "bg-accent-soft" : "bg-transparent")}
    >
      <div className="w-6 text-center text-[12.5px] font-semibold text-text-dim">
        {row.rank}
      </div>
      <Avatar name={row.name} size={30} />
      <div className="flex-1 min-w-0 flex items-center gap-2">
        <span className="text-md font-medium overflow-hidden text-ellipsis whitespace-nowrap">
          {row.name}
        </span>
        {row.is_you && <span className="chip chip--accent">You</span>}
      </div>
      <div className="text-[11.5px] text-text-muted whitespace-nowrap">
        {row.stage} · Lvl {row.level}
      </div>
      <div className="text-[11.5px] text-text-muted whitespace-nowrap w-16 text-right">
        {row.streak} day{row.streak === 1 ? "" : "s"}
      </div>
      <div className="text-md font-semibold w-19 text-right">
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
    <div className="py-6 px-8">
      <div className="flex justify-between items-center mb-4.5 gap-3 flex-wrap">
        <Toggle options={SCOPES} value={scope} onChange={setScope} />
        {resetsAt && (
          <div className="text-[11.5px] text-text-muted">
            Weekly board {formatResetTimer(resetsAt)}
          </div>
        )}
      </div>

      {loading && (
        <div className="py-15 px-8 text-center text-text-muted text-md">
          Loading leaderboard…
        </div>
      )}

      {!loading && error && (
        <div className="py-15 px-8 text-center text-text-muted text-md">
          Couldn&apos;t load the leaderboard right now.
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="py-15 px-8 text-center text-text-muted text-md">
          No XP earned in this group yet this week.
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          <Podium rows={podiumRows} />
          <div className="card p-2">
            {rows.map((row) => <RankRow key={row.user_id} row={row} />)}
          </div>
          {viewerRow && !rows.some((r) => r.user_id === viewerRow.user_id) && (
            // Defensive only: today the viewer's row is always inside `rows`,
            // but if that ever changes, still surface their standing rather
            // than silently omitting it. Checked by user_id, not rank — rank
            // contiguity is an implementation detail of the current
            // unpaginated backend, not something the LeaderboardRow type
            // guarantees (xp_events already grew pagination once, #Task 8).
            <div className="card p-2 mt-2.5">
              <RankRow row={viewerRow} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
