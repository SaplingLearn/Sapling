// @vitest-environment jsdom
/**
 * The learning-loop help-abuse section (spec §13 A133): what it shows from
 * the admin KPI's `help_abuse` field, that nothing renders for a backend
 * before A133, that a failed read says so, and that "nothing behind it" reads
 * as "—", never a zero.
 */

import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { HelpAbusePanel, STUDENT_ROWS } from "./HelpAbusePanel";
import type { LoopHelpAbuse, LoopHelpAbuseGroup } from "@/lib/types";

afterEach(cleanup);

const next = (graded = 0, unassisted_correct = 0, other = 0, none = 0) => ({ graded, unassisted_correct, other, none });

function group(key: string, over: Partial<LoopHelpAbuseGroup> = {}): LoopHelpAbuseGroup {
  return {
    key,
    steps: 4,
    bottom_outs: 1,
    full_solutions: 1,
    bottom_out_rate: 0.25,
    time_to_bottom_out_s: { n: 1, median: 77 },
    help_gap_s: { n: 5, median: 8 },
    climb_gap_s: { n: 4, median: 8 },
    attempts: { counted: 6, rapid: 5, repeat: 0, strict_refused: 0 },
    bottom_out_attempts: { measured: 1, unmeasured: 0, held_by_strict: 1, no_strict_attempt: 0 },
    next: { none: next(2, 2, 0, 0), partial: next(1, 1, 0, 0), bottom_out: next(1, 0, 1, 0) },
    ...over,
  };
}

/** The six one-character attempts' student, a genuine one and an untouched step. */
const report: LoopHelpAbuse = {
  bottom_out_rung: 5,
  overall: group("all"),
  by_band: [group("develop"), group("unknown", { steps: 1, bottom_outs: 0, full_solutions: 0, bottom_out_rate: 0 })],
  by_gate: [
    group("standard"),
    group("strict", {
      bottom_outs: 0, full_solutions: 0, bottom_out_rate: 0,
      time_to_bottom_out_s: { n: 0, median: null },
      attempts: { counted: 2, rapid: 0, repeat: 0, strict_refused: 3 },
      bottom_out_attempts: { measured: 0, unmeasured: 0, held_by_strict: 0, no_strict_attempt: 0 },
      next: { none: next(), partial: next(), bottom_out: next() },
    }),
  ],
  by_course: [group("course-1")],
  by_student: [group("u-spam"), group("u-genuine", { bottom_outs: 0, full_solutions: 0, bottom_out_rate: 0 })],
  truncated: false,
};

describe("HelpAbusePanel (spec §13 A133)", () => {
  it("renders nothing for a backend before A133, and says so when the reads failed", () => {
    const { container } = render(<HelpAbusePanel data={undefined} />);
    expect(container.innerHTML).toBe("");
    cleanup();
    render(<HelpAbusePanel data={null} />);
    expect(screen.getByTestId("admin-loop-help-abuse-unavailable").textContent).toContain("could not be read");
  });

  it("shows the headline numbers and the bottom-out rung", () => {
    render(<HelpAbusePanel data={report} />);
    const overall = screen.getByTestId("admin-loop-help-abuse-overall");
    expect(overall.textContent).toContain("1 (25%)");
    expect(overall.textContent).toContain("77 s");
    expect(overall.textContent).toContain("8 s");
    expect(screen.getByTestId("admin-loop-help-abuse").textContent).toContain("H5");
  });

  it("compares the gates: attempts, the strict rule's holds and refusals, and the next item", () => {
    render(<HelpAbusePanel data={report} />);
    const standard = screen.getByTestId("admin-loop-help-abuse-gate-standard");
    expect(within(standard).getByText("Standard gate")).toBeTruthy();
    expect(within(standard).getByText("5 / 0 of 6")).toBeTruthy(); // rapid / repeat of counted
    expect(within(standard).getByText("1 of 1")).toBeTruthy(); // bottom-outs the strict rule would hold
    expect(within(standard).getByText("0 of 1 (0%)")).toBeTruthy(); // next right unaided, after a bottom-out
    const strict = screen.getByTestId("admin-loop-help-abuse-gate-strict");
    expect(within(strict).getByText("Strict gate")).toBeTruthy();
    // nothing behind a value reads "—", never a zero
    expect(within(strict).getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("labels bands, and lists courses and students", () => {
    render(<HelpAbusePanel data={report} />);
    expect(within(screen.getByTestId("admin-loop-help-abuse-band-develop")).getByText("Developing")).toBeTruthy();
    expect(within(screen.getByTestId("admin-loop-help-abuse-band-unknown")).getByText("Band unknown")).toBeTruthy();
    expect(screen.getByTestId("admin-loop-help-abuse-course-course-1")).toBeTruthy();
    const students = screen.getByTestId("admin-loop-help-abuse-student");
    expect(within(students).getAllByRole("row").map(r => r.getAttribute("data-testid"))).toEqual([
      null, // the header
      "admin-loop-help-abuse-student-u-spam",
      "admin-loop-help-abuse-student-u-genuine",
    ]);
  });

  it("shows the next-item outcomes by the help the item got", () => {
    render(<HelpAbusePanel data={report} />);
    const bottom = screen.getByTestId("admin-loop-help-abuse-next-bottom_out");
    expect(within(bottom).getByText("Bottomed out (H5–H6)")).toBeTruthy();
    expect(within(bottom).getByText("0 of 1 (0%)")).toBeTruthy();
    const none = screen.getByTestId("admin-loop-help-abuse-next-none");
    expect(within(none).getByText("2 of 2 (100%)")).toBeTruthy();
  });

  it("names what it cannot measure", () => {
    render(<HelpAbusePanel data={report} />);
    expect(screen.getByTestId("admin-loop-help-abuse-limits").textContent).toContain(
      "never graded and their text is never stored",
    );
  });

  it("shows the top students first and all of them on request", () => {
    const many = { ...report, by_student: Array.from({ length: STUDENT_ROWS + 3 }, (_, i) => group(`u${i}`)) };
    render(<HelpAbusePanel data={many} />);
    const rows = () => within(screen.getByTestId("admin-loop-help-abuse-student")).getAllByRole("row").length - 1;
    expect(rows()).toBe(STUDENT_ROWS);
    const toggle = screen.getByTestId("admin-loop-help-abuse-students-toggle");
    expect(toggle.textContent).toBe(`Show all ${STUDENT_ROWS + 3} students`);
    fireEvent.click(toggle);
    expect(rows()).toBe(STUDENT_ROWS + 3);
    fireEvent.click(toggle);
    expect(rows()).toBe(STUDENT_ROWS);
  });

  it("says when a group has no posed item", () => {
    render(<HelpAbusePanel data={{ ...report, by_course: [] }} />);
    expect(screen.getByTestId("admin-loop-help-abuse-course").textContent).toContain("No posed check items");
  });
});
