/**
 * The redesigned calendar's model (calendar/v2/calendarModel.ts): which items
 * there are, how the agenda groups them, the grids, and the week loads.
 * "Today" is Wed, Mar 11 2026, the boards' day.
 */
import { describe, expect, it } from "vitest";
import type { Assignment, EnrolledCourse } from "@/lib/api";
import {
  agendaOf, busiestWeek, countdown, coursesOf, labelRows, loadText, monthCells, monthLine, rangeText, startOfWeek,
  timelinePos, toItems, weekCells, weekLine, weekLoads,
} from "./calendarModel";

const TODAY = new Date(2026, 2, 11);
const course = (id: string, code: string, color: string | null = null) =>
  ({ course_id: id, course_code: code, course_name: `${code} name`, color } as EnrolledCourse);
const COURSES = [course("cs", "CS 112", "#123456"), course("ma", "MA 123")];
const a = (id: string, title: string, due: string | null, course_id: string, assignment_type = "homework") =>
  ({ id, user_id: "u1", title, due_date: due, course_id, assignment_type } as Assignment);
const ASSIGNMENTS = [
  a("mid1", "Midterm Exam", "2026-03-02", "cs", "exam"),
  a("hw7", "HW 7", "2026-03-12T23:59:00", "cs"),
  a("q4", "Quiz 4", "2026-03-13", "ma", "quiz"),
  a("lab", "Lab report", "2026-03-16", "ma"),
  a("mid2", "Midterm 2", "2026-03-20", "cs", "exam"),
  a("mid3", "Midterm", "2026-03-30", "ma", "exam"),
  a("prop", "Project proposal", "2026-03-31", "cs"),
  a("prac", "Lab practical", "2026-04-01", "ma", "exam"),
  a("nodate", "Reading", null, "cs"),
];
const ITEMS = toItems(ASSIGNMENTS, COURSES);

describe("items", () => {
  it("leaves undated work out, sorts by day, types and colours each", () => {
    expect(ITEMS.map((i) => i.id)).toEqual(["mid1", "hw7", "q4", "lab", "mid2", "mid3", "prop", "prac"]);
    expect(ITEMS.find((i) => i.id === "q4")!.kind).toBe("Quiz");
    expect(ITEMS.find((i) => i.id === "mid2")!.kind).toBe("Exam");
    expect(ITEMS.find((i) => i.id === "hw7")!.iso).toBe("2026-03-12");
    expect(ITEMS[0].color).toBe("#123456");
    expect(ITEMS.find((i) => i.id === "q4")!.course).toBe("MA 123");
    expect(coursesOf(ITEMS).map((c) => c.label)).toEqual(["CS 112", "MA 123"]);
  });

  it("counts down in words", () => {
    expect(countdown(new Date(2026, 2, 11), TODAY)).toBe("Today");
    expect(countdown(new Date(2026, 2, 12), TODAY)).toBe("Tomorrow");
    expect(countdown(new Date(2026, 2, 20), TODAY)).toBe("In 9 days");
    expect(countdown(new Date(2026, 2, 2), TODAY)).toBe("9 days ago");
  });
});

describe("the agenda", () => {
  it("groups what is ahead by week and keeps the past apart", () => {
    const { earlier, groups } = agendaOf(ITEMS, TODAY);
    expect(earlier.map((i) => i.id)).toEqual(["mid1"]);
    expect(groups.map((g) => [g.name, g.range, g.items.map((i) => i.id)])).toEqual([
      ["This week", "Mar 9 – 15", ["hw7", "q4"]],
      ["Next week", "Mar 16 – 22", ["lab", "mid2"]],
      ["Later", "Mar 23 – Apr 1", ["mid3", "prop", "prac"]],
    ]);
    expect(weekLine(ITEMS, TODAY)).toBe("2 due this week, the next one tomorrow");
    expect(weekLine([], TODAY)).toBe("Nothing due this week");
  });
});

describe("grids", () => {
  it("a month is six Monday-first weeks, today marked", () => {
    const cells = monthCells(TODAY, ITEMS, TODAY);
    expect(cells).toHaveLength(42);
    expect(cells[0].iso).toBe("2026-02-23");
    expect(cells.find((c) => c.today)!.iso).toBe("2026-03-11");
    expect(cells.find((c) => c.iso === "2026-03-02")!.items.map((i) => i.id)).toEqual(["mid1"]);
    expect(cells[0].inMonth).toBe(false);
    expect(cells.find((c) => c.iso === "2026-03-14")!.weekend).toBe(true);
    expect(monthLine(TODAY, ITEMS)).toBe("7 due in March, 3 of them exams");
  });

  it("a week is Monday to Sunday", () => {
    const cells = weekCells(TODAY, ITEMS, TODAY);
    expect(cells.map((c) => c.iso)).toEqual(["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-14", "2026-03-15"]);
    expect(startOfWeek(new Date(2026, 2, 15)).getDate()).toBe(9);
    expect(rangeText(new Date(2026, 2, 30), new Date(2026, 3, 5))).toBe("Mar 30 – Apr 5");
  });
});

describe("week loads", () => {
  it("counts each week and finds the heaviest ahead", () => {
    const loads = weekLoads(new Date(2026, 2, 2), 5, ITEMS);
    expect(loads.map((w) => [w.label, w.count, w.exams])).toEqual([
      ["Mar 2", 1, 1], ["Mar 9", 2, 0], ["Mar 16", 2, 1], ["Mar 23", 0, 0], ["Mar 30", 3, 2],
    ]);
    expect(loadText(loads[4])).toBe("3 due, 2 exams");
    expect(loadText(loads[3])).toBe("Nothing due");
    const busy = busiestWeek(ITEMS, TODAY)!;
    expect(busy.range).toBe("Mar 30 – Apr 5");
    expect(busy.items.map((i) => i.id)).toEqual(["mid3", "prop", "prac"]);
    expect(busiestWeek(ITEMS.slice(0, 3), TODAY)).toBeNull();
    expect(timelinePos(new Date(2026, 2, 16), new Date(2026, 2, 2), 2)).toBe(1);
  });

  it("a busiest-week tie goes to the week with more exams", () => {
    const tie = toItems([
      a("x1", "HW 1", "2026-03-16", "cs"), a("x2", "HW 2", "2026-03-17", "cs"), a("x3", "Midterm", "2026-03-18", "cs", "exam"),
      a("y1", "Final", "2026-03-23", "cs", "exam"), a("y2", "Exam 2", "2026-03-24", "ma", "exam"), a("y3", "HW 3", "2026-03-25", "ma"),
    ], COURSES);
    expect(busiestWeek(tie, TODAY)!.range).toBe("Mar 23 – 29");
  });

  it("timeline labels stagger into rows so close ones never overlap; a fourth crowded one hides", () => {
    const d = (n: number) => ({ day: new Date(2026, 2, n) });
    expect(labelRows([d(1), d(3), d(5), d(6), d(8), d(20)]).map((r) => r.row)).toEqual([0, 1, 2, -1, 0, 0]);
  });
});
