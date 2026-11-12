import { describe, it, expect } from "vitest";
import type { StudyDaily, StudyDay } from "@/lib/studyApi";
import { DEFAULT_GOAL, dayBar, goalStats } from "./dailyGoalModel";

const day = (date: string, minutes: number): StudyDay =>
  ({ date, minutes, quiz: minutes, flashcards: 0, tutor: 0, quizzes: 0, cards: 0, sessions: 0 });
const daily = (goal: number, minutes: number[]): StudyDaily => ({
  goal_minutes: goal,
  today: `2026-11-0${minutes.length}`,
  days: minutes.map((m, i) => day(`2026-11-0${i + 1}`, m)),
});

describe("goalStats", () => {
  it("reads today off the last day and counts the earlier days that met the goal", () => {
    const stats = goalStats(daily(40, [10, 40, 55, 0, 25]));
    expect(stats).toMatchObject({ goal: 40, done: 25, met: false, hit: 2, pastDays: 4, weekTotal: 130 });
    expect(stats.pct).toBe(62.5);
    expect(stats.today?.date).toBe("2026-11-05");
  });

  it("caps today's progress at the goal", () => {
    expect(goalStats(daily(30, [0, 90]))).toMatchObject({ done: 90, met: true, pct: 100 });
  });

  it("the chart's ceiling clears the goal line, or the tallest day", () => {
    expect(goalStats(daily(40, [10, 20])).max).toBe(50);
    expect(goalStats(daily(40, [10, 120])).max).toBe(120);
  });

  it("before the read answers it is an empty week under the default goal", () => {
    expect(goalStats(null)).toMatchObject({
      goal: DEFAULT_GOAL, week: [], today: undefined, done: 0, pct: 0, met: false, hit: 0, pastDays: 0, weekTotal: 0,
    });
  });
});

describe("dayBar", () => {
  it("an empty day is a stub", () => {
    expect(dayBar(0, false, 30, 60)).toEqual({ height: 3, background: "var(--bg-soft)" });
    expect(dayBar(0, true, 30, 60)).toEqual({ height: 3, background: "var(--bg-soft)" });
  });

  it("scales to the chart's ceiling, never shorter than 6%", () => {
    expect(dayBar(30, false, 30, 60).height).toBe("50%");
    expect(dayBar(1, false, 30, 60).height).toBe("6%");
    expect(dayBar(90, false, 30, 60).height).toBe("100%");
  });

  it("colours today, a day that met the goal, and one that did not", () => {
    expect(dayBar(10, true, 30, 60).background).toBe("var(--brand-forest)");
    expect(dayBar(30, false, 30, 60).background).toBe("var(--sap-300)");
    expect(dayBar(29, false, 30, 60).background).toBe("var(--ink-200)");
  });
});
