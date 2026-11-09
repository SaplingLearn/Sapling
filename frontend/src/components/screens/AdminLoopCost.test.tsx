// @vitest-environment jsdom
/**
 * The learning loop's cost against its measured gain (spec §13 A137): every
 * figure with its n, "—" (never a zero) when there is nothing to divide by,
 * "no net gain" when pairs exist without a gain, an open upper bound read as
 * "unbounded", the per-course table, the unattributed spend, and the two
 * missing states (a failed read; a backend that predates the field).
 */

import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { LoopCostPanel, fmtUsd } from "./AdminLoopCost";
import type { LoopCostBlock, LoopCostPerGain, LoopCostWindow } from "@/lib/types";

afterEach(cleanup);

const window7: LoopCostWindow = {
  window_days: 7, pairs: 12, students: 5, gain_points: 4,
  per_pair: 0.0617, per_pair_ci: [0.04, 0.09],
  per_gain_point: 0.185, per_gain_point_ci: [0.1, null],
};
const window28: LoopCostWindow = {
  window_days: 28, pairs: 3, students: 1, gain_points: 0,
  per_pair: 0.2467, per_pair_ci: null, per_gain_point: null, per_gain_point_ci: null,
};

function block(over: Partial<LoopCostBlock> = {}): LoopCostBlock {
  return {
    course_id: null, cost_usd: 0.74, tutor_usd: 0.5, drafting_usd: 0.12, rows: 420, unpriced_rows: 0,
    active_students: 5, per_active_student_month: 0.148, tutor_per_active_student_month: 0.1,
    target_ratio: 0.411, sessions: 8, per_session: 0.0775, windows: [window7, window28], ...over,
  };
}

function report(over: Partial<LoopCostPerGain> = {}): LoopCostPerGain {
  return {
    target_usd_per_student_month: 0.36, range_days: 30,
    ci: { method: "student_cluster_bootstrap_percentile", level: 0.95, resamples: 2000, seed: "s" },
    overall: block(),
    courses: [block({ course_id: "cs101", cost_usd: 0.7 })],
    unattributed: { cost_usd: 0, rows: 0 },
    ...over,
  };
}

describe("LoopCostPanel", () => {
  it("shows each rate with its n and the target", () => {
    render(<LoopCostPanel cost={report()} />);
    const month = screen.getByTestId("admin-loop-cost-student-month");
    expect(month).toHaveTextContent("$0.148");
    expect(month).toHaveTextContent("5 active students");
    expect(month).toHaveTextContent("0.4× the $0.36 target");
    expect(screen.getByTestId("admin-loop-cost-session")).toHaveTextContent("$0.0775");
    expect(screen.getByTestId("admin-loop-cost-session")).toHaveTextContent("8 sessions");
    expect(screen.getByTestId("admin-loop-cost-tutor-month")).toHaveTextContent("$0.1");
    expect(screen.getByTestId("admin-loop-cost-total")).toHaveTextContent("420 model calls, drafting $0.12");
  });

  it("reads each window's pairs, gain and intervals, an open bound as unbounded", () => {
    render(<LoopCostPanel cost={report()} />);
    const seven = screen.getByTestId("admin-loop-cost-window-7");
    expect(seven).toHaveTextContent("12 (5 students)");
    expect(seven).toHaveTextContent("+4");
    expect(screen.getByTestId("admin-loop-cost-window-7-pair-ci")).toHaveTextContent("$0.04 to $0.09");
    expect(screen.getByTestId("admin-loop-cost-window-7-gain-ci")).toHaveTextContent("$0.1 to unbounded");
    // pairs but no net gain: said so, never a price; one student: no interval
    expect(screen.getByTestId("admin-loop-cost-window-28-gain")).toHaveTextContent("no net gain");
    expect(screen.queryByTestId("admin-loop-cost-window-28-pair-ci")).toBeNull();
  });

  it("puts nothing to divide by as a dash, never a zero", () => {
    const empty: LoopCostWindow = {
      window_days: 7, pairs: 0, students: 0, gain_points: 0,
      per_pair: null, per_pair_ci: null, per_gain_point: null, per_gain_point_ci: null,
    };
    const none = block({
      cost_usd: 0, tutor_usd: 0, drafting_usd: 0, rows: 0, active_students: 0,
      per_active_student_month: null, tutor_per_active_student_month: null, target_ratio: null,
      sessions: 0, per_session: null, windows: [empty],
    });
    render(<LoopCostPanel cost={report({ overall: none, courses: [] })} />);
    expect(screen.getByTestId("admin-loop-cost-student-month")).toHaveTextContent("—");
    expect(screen.getByTestId("admin-loop-cost-student-month")).toHaveTextContent("target $0.36");
    expect(screen.getByTestId("admin-loop-cost-session")).toHaveTextContent("—");
    expect(screen.getByTestId("admin-loop-cost-window-7-gain")).toHaveTextContent("—");
    expect(screen.queryByTestId("admin-loop-cost-courses")).toBeNull();
  });

  it("lists the courses and the unattributed spend", () => {
    render(<LoopCostPanel cost={report({ unattributed: { cost_usd: 0.04, rows: 3 } })} />);
    const course = screen.getByTestId("admin-loop-cost-course-cs101");
    expect(within(course).getByText("cs101")).toBeInTheDocument();
    expect(course).toHaveTextContent("$0.7");
    expect(course).toHaveTextContent("12 / +4");
    expect(screen.getByTestId("admin-loop-cost-unattributed")).toHaveTextContent("$0.04 over 3 calls");
  });

  it("says when the spend could not be read, and shows nothing for an older backend", () => {
    const { container, rerender } = render(<LoopCostPanel cost={null} />);
    expect(screen.getByTestId("admin-loop-cost-unavailable")).toBeInTheDocument();
    rerender(<LoopCostPanel cost={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("formats sub-cent dollars readably", () => {
    expect(fmtUsd(null)).toBe("—");
    expect(fmtUsd(0)).toBe("$0");
    expect(fmtUsd(0.00004)).toBe("<$0.0001");
    expect(fmtUsd(0.0123)).toBe("$0.0123");
    expect(fmtUsd(0.36)).toBe("$0.36");
    expect(fmtUsd(0.14837)).toBe("$0.148");
    expect(fmtUsd(12.345)).toBe("$12.35");
  });
});
