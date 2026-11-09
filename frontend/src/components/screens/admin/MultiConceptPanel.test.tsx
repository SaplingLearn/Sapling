// @vitest-environment jsdom
/**
 * The learning-loop multi-concept section (spec §13 A141): served and
 * outcomes per course with every n, nothing for a backend before A141, a
 * failed read said so, and a rate with nothing behind it "—", never a zero.
 */

import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { LoopMultiConcept, LoopMultiConceptBlock } from "@/lib/types";
import { MultiConceptPanel, rateWithCi } from "./MultiConceptPanel";

afterEach(cleanup);

function block(over: Partial<LoopMultiConceptBlock> = {}): LoopMultiConceptBlock {
  return {
    course_id: "c1",
    items: 6,
    held: 1,
    served: 9,
    answered: 8,
    correct: 5,
    unassisted: 6,
    unassisted_correct: 4,
    students: 3,
    correct_rate: 0.625,
    correct_ci_low: 0.306,
    correct_ci_high: 0.863,
    ...over,
  };
}

describe("MultiConceptPanel (spec §13 A141)", () => {
  it("renders nothing for a backend before A141", () => {
    const { container } = render(<MultiConceptPanel data={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says when the data could not be read", () => {
    render(<MultiConceptPanel data={null} />);
    expect(screen.getByTestId("admin-loop-multi-concept-unavailable")).toBeInTheDocument();
  });

  it("shows served and outcomes per course and overall, each with its n", () => {
    const data: LoopMultiConcept = {
      overall: block({ course_id: null }),
      courses: [block(), block({ course_id: "c2", answered: 0, correct: 0, unassisted: 0, unassisted_correct: 0, students: 0, correct_rate: null, correct_ci_low: null, correct_ci_high: null, held: 0 })],
    };
    render(<MultiConceptPanel data={data} />);
    const c1 = screen.getByTestId("admin-loop-multi-concept-course-c1");
    expect(c1).toHaveTextContent("6 (1 held)");
    expect(c1).toHaveTextContent("4 of 6");
    expect(c1).toHaveTextContent("62.5% (30.6%–86.3%) of 8");
    const c2 = screen.getByTestId("admin-loop-multi-concept-course-c2");
    expect(c2).toHaveTextContent("—");
    expect(c2).not.toHaveTextContent("0%");
    expect(screen.getByTestId("admin-loop-multi-concept-overall")).toHaveTextContent("All courses");
  });

  it("says when nothing is stored yet", () => {
    render(<MultiConceptPanel data={{ overall: block({ course_id: null, items: 0, held: 0, served: 0, answered: 0, correct: 0, unassisted: 0, unassisted_correct: 0, students: 0, correct_rate: null, correct_ci_low: null, correct_ci_high: null }), courses: [] }} />);
    expect(screen.getByTestId("admin-loop-multi-concept-empty")).toBeInTheDocument();
  });

  it("formats a rate with nothing behind it as a dash, never a zero", () => {
    expect(rateWithCi(block({ correct_rate: null, answered: 0 }))).toBe("—");
    expect(rateWithCi(block({ correct_ci_low: null, correct_ci_high: null }))).toBe("62.5% of 8");
  });
});
