import { describe, it, expect } from "vitest";
import { barHeights, computeGoalY } from "./ActivityTab";

describe("barHeights", () => {
  it("scales the tallest bar to the chart height", () => {
    expect(barHeights([50, 100], 100, 140)).toEqual([70, 140]);
  });

  it("gives a zero value a visible stub", () => {
    expect(barHeights([0, 100], 100, 140)).toEqual([4, 140]);
  });

  it("returns stubs when every value is zero", () => {
    expect(barHeights([0, 0, 0], 0, 140)).toEqual([4, 4, 4]);
  });
});

describe("computeGoalY", () => {
  it("lands at the same height as a bar of the same XP value — a mismatched scale would silently lie about hitting the goal", () => {
    const scaleMax = 100;
    const chartH = 140;
    const dailyGoalXp = 50;
    const goalHeightFromBottom = chartH - computeGoalY(dailyGoalXp, scaleMax, chartH);
    const [barHeight] = barHeights([dailyGoalXp], scaleMax, chartH);
    expect(goalHeightFromBottom).toBe(barHeight);
  });

  it("still agrees with a bar of the same value at a different scale", () => {
    const scaleMax = 230; // e.g. Math.max(...xps, dailyGoalXp) * 1.15
    const chartH = 140;
    const dailyGoalXp = 60;
    const goalHeightFromBottom = chartH - computeGoalY(dailyGoalXp, scaleMax, chartH);
    const [barHeight] = barHeights([dailyGoalXp], scaleMax, chartH);
    expect(goalHeightFromBottom).toBe(barHeight);
  });

  it("puts a zero goal at the very bottom of the chart", () => {
    expect(computeGoalY(0, 100, 140)).toBe(140);
  });

  it("doesn't divide by zero when the week and the goal are both empty", () => {
    // Mirrors WeeklyChart's `Math.max(...xps, dailyGoalXp) * 1.15 || 1` fallback:
    // an all-zero week with no goal set still yields a finite, on-chart position.
    const goalY = computeGoalY(0, 0, 140);
    expect(Number.isFinite(goalY)).toBe(true);
    expect(goalY).toBe(140);
  });
});
