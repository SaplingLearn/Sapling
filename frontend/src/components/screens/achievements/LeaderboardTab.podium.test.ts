import { describe, it, expect } from "vitest";
import { buildPodiumSpots } from "./LeaderboardTab";
import type { LeaderboardRow } from "@/lib/types";

function row(rank: number): LeaderboardRow {
  return {
    rank,
    user_id: `u${rank}`,
    name: `User ${rank}`,
    level: 1,
    stage: "Sapling",
    total_xp: 0,
    week_xp: 100 - rank,
    streak: 0,
    is_you: false,
  };
}

describe("buildPodiumSpots", () => {
  it("returns no spots for an empty board", () => {
    expect(buildPodiumSpots([])).toEqual([]);
  });

  it("returns a single centered 1st-place spot for one row — the case a naive rows[1] would crash on", () => {
    const rows = [row(1)];
    expect(buildPodiumSpots(rows)).toEqual([
      { row: rows[0], place: 1 },
    ]);
  });

  it("returns 2nd-then-1st for two rows, with no 3rd-place slot — the other naive-index crash case", () => {
    const rows = [row(1), row(2)];
    expect(buildPodiumSpots(rows)).toEqual([
      { row: rows[1], place: 2 },
      { row: rows[0], place: 1 },
    ]);
  });

  it("returns 2nd, 1st, 3rd in that visual order for three rows", () => {
    const rows = [row(1), row(2), row(3)];
    expect(buildPodiumSpots(rows)).toEqual([
      { row: rows[1], place: 2 },
      { row: rows[0], place: 1 },
      { row: rows[2], place: 3 },
    ]);
  });

  it("ignores anything past the top three when given more rows", () => {
    const rows = [row(1), row(2), row(3), row(4)];
    expect(buildPodiumSpots(rows)).toEqual([
      { row: rows[1], place: 2 },
      { row: rows[0], place: 1 },
      { row: rows[2], place: 3 },
    ]);
  });
});
