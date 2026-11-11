// @vitest-environment jsdom
/**
 * GradePredictorPanel — characterization of the per-assignment slider row
 * (AssignmentSliderRow): derived display values (possible / earned / slider
 * max / pts label / warning / due line), the earned + total + class-stat
 * inputs' emitted scores, and the curve section. Pins behavior before the
 * complexity split; the row is reached through the exported panel.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { GradePredictorPanel } from "./GradePredictorPanel";
import type { GradedAssignment, GradeCategory } from "@/lib/types";

type Hyp = {
  earned: number;
  possible: number;
  curveClassMean: number | null;
  curveClassSd: number | null;
};

afterEach(cleanup);

function makeAssignment(over: Partial<GradedAssignment> = {}): GradedAssignment {
  return {
    id: "a1",
    title: "Problem Set 3",
    course_id: "c1",
    category_id: "cat1",
    points_possible: 40,
    points_earned: null,
    due_date: "2026-03-07",
    assignment_type: null,
    notes: null,
    source: "manual",
    curve_class_mean: null,
    curve_class_sd: null,
    curve_avg_target: null,
    curve_sd_delta: null,
    ...over,
  };
}

const categories: GradeCategory[] = [
  { id: "cat1", name: "Homework", weight: 1, sort_order: 0, drop_lowest: 0 },
];

function renderRow(
  assignment: GradedAssignment,
  hyp: Hyp | undefined = undefined,
  opts: { curve?: boolean } = {},
) {
  const onHypotheticalChange = vi.fn();
  const hypotheticals = new Map<string, Hyp>();
  if (hyp !== undefined) hypotheticals.set(assignment.id, hyp);
  const utils = render(
    <GradePredictorPanel
      open
      onToggle={() => {}}
      ungradedAssignments={[assignment]}
      categories={categories}
      hypotheticals={hypotheticals}
      onHypotheticalChange={onHypotheticalChange}
      onReset={() => {}}
      predictedPercent={null}
      predictedLetter={null}
      isCurved={!!opts.curve}
      predictorCurveEnabled={!!opts.curve}
      onTogglePredictorCurve={() => {}}
    />,
  );
  const slider = utils.container.querySelector('input[type="range"]') as HTMLInputElement;
  const numbers = Array.from(
    utils.container.querySelectorAll('input[type="number"]'),
  ) as HTMLInputElement[];
  return { ...utils, onHypotheticalChange, slider, numbers };
}

describe("AssignmentSliderRow — derived display", () => {
  it("assignment with a stored total: half-default earned, total as text, no warning", () => {
    const { slider, numbers, container } = renderRow(makeAssignment());
    expect(slider.max).toBe("40");
    expect(slider.value).toBe("20");
    expect(numbers).toHaveLength(1);
    expect(numbers[0].value).toBe("20");
    expect(screen.getByText("40 pts")).toBeTruthy();
    expect(container.textContent).toContain("Homework · Due 03/07/2026");
    expect(screen.queryByText("⚠ No Total Score")).toBeNull();
    expect(screen.getByText("40", { selector: "span" })).toBeTruthy();
  });

  it("rounds the default earned (odd total)", () => {
    const { numbers } = renderRow(makeAssignment({ points_possible: 15 }));
    // Math.round(7.5) = 8
    expect(numbers[0].value).toBe("8");
  });

  it("no total, no hypothetical: 100 default, warning, '— pts', empty total input", () => {
    const { slider, numbers } = renderRow(makeAssignment({ points_possible: null }));
    expect(slider.max).toBe("100");
    expect(numbers[0].value).toBe("50");
    expect(numbers).toHaveLength(2);
    expect(numbers[1].value).toBe("");
    expect(numbers[1].placeholder).toBe("—");
    expect(screen.getByText("⚠ No Total Score")).toBeTruthy();
    expect(screen.getByText("— pts")).toBeTruthy();
  });

  it("points_possible 0 counts as no total", () => {
    const { slider, numbers } = renderRow(makeAssignment({ points_possible: 0 }));
    expect(slider.max).toBe("100");
    expect(numbers).toHaveLength(2);
    expect(screen.getByText("⚠ No Total Score")).toBeTruthy();
  });

  it("negative points_possible counts as no total", () => {
    const { numbers } = renderRow(makeAssignment({ points_possible: -5 }));
    expect(numbers).toHaveLength(2);
    expect(screen.getByText("— pts")).toBeTruthy();
  });

  it("no stored total but a hypothetical total: uses it, no warning", () => {
    const { slider, numbers } = renderRow(makeAssignment({ points_possible: null }), {
      earned: 7,
      possible: 12.5,
      curveClassMean: null,
      curveClassSd: null,
    });
    expect(slider.max).toBe("12.5");
    expect(numbers[0].value).toBe("7");
    expect(numbers[1].value).toBe("12.5");
    expect(screen.getByText("12.5 pts")).toBeTruthy();
    expect(screen.queryByText("⚠ No Total Score")).toBeNull();
  });

  it("hypothetical total 0: slider max falls back to 100, warning + '— pts', total input shows 0", () => {
    const { slider, numbers } = renderRow(makeAssignment({ points_possible: null }), {
      earned: 0,
      possible: 0,
      curveClassMean: null,
      curveClassSd: null,
    });
    expect(slider.max).toBe("100");
    expect(numbers[0].value).toBe("0");
    expect(numbers[1].value).toBe("0");
    expect(screen.getByText("⚠ No Total Score")).toBeTruthy();
    expect(screen.getByText("— pts")).toBeTruthy();
  });

  it("hypothetical total overrides the stored total in the pts label but the text total stays stored", () => {
    const { slider } = renderRow(makeAssignment({ points_possible: 40 }), {
      earned: 10,
      possible: 50,
      curveClassMean: null,
      curveClassSd: null,
    });
    expect(slider.max).toBe("50");
    expect(screen.getByText("50 pts")).toBeTruthy();
    expect(screen.getByText("40", { selector: "span" })).toBeTruthy();
  });

  it("no due date: meta shows only the category", () => {
    const { container } = renderRow(makeAssignment({ due_date: null }));
    const meta = Array.from(container.querySelectorAll("div.mono")).find((d) =>
      d.textContent?.startsWith("Homework"),
    );
    expect(meta?.textContent).toBe("Homework");
  });

  it("unknown category renders Uncategorized", () => {
    const { container } = renderRow(makeAssignment({ category_id: "nope" }));
    expect(container.textContent).toContain("Uncategorized · Due 03/07/2026");
  });
});

describe("AssignmentSliderRow — earned inputs", () => {
  it("slider change emits clamped earned with the current possible + stored curve stats", () => {
    const { slider, onHypotheticalChange } = renderRow(
      makeAssignment({ curve_class_mean: 0.7, curve_class_sd: 0.1 }),
    );
    fireEvent.change(slider, { target: { value: "12.5" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 12.5,
      possible: 40,
      curveClassMean: 0.7,
      curveClassSd: 0.1,
    });
  });

  it("earned number input clamps over-max to possible and negatives to 0", () => {
    const { numbers, onHypotheticalChange } = renderRow(makeAssignment());
    fireEvent.change(numbers[0], { target: { value: "55" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 40 }));
    fireEvent.change(numbers[0], { target: { value: "-3" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 0 }));
    fireEvent.change(numbers[0], { target: { value: "3.25" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 3.25 }));
  });

  it("clearing the earned input emits earned 0 (Number('') is 0)", () => {
    const { numbers, onHypotheticalChange } = renderRow(makeAssignment());
    fireEvent.change(numbers[0], { target: { value: "" } });
    expect(onHypotheticalChange).toHaveBeenCalledTimes(1);
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 0,
      possible: 40,
      curveClassMean: null,
      curveClassSd: null,
    });
  });

  it("hypothetical with possible 0 clamps any earned to 0", () => {
    const { numbers, onHypotheticalChange } = renderRow(makeAssignment({ points_possible: null }), {
      earned: 0,
      possible: 0,
      curveClassMean: null,
      curveClassSd: null,
    });
    fireEvent.change(numbers[0], { target: { value: "9" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 0, possible: 0 }));
  });
});

describe("AssignmentSliderRow — total input", () => {
  it("a positive total emits possible and caps earned at it", () => {
    const { numbers, onHypotheticalChange } = renderRow(makeAssignment({ points_possible: null }));
    fireEvent.change(numbers[1], { target: { value: "30" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 30,
      possible: 30,
      curveClassMean: null,
      curveClassSd: null,
    });
    fireEvent.change(numbers[1], { target: { value: "200" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 50, possible: 200 }));
    fireEvent.change(numbers[1], { target: { value: "0.5" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ earned: 0.5, possible: 0.5 }));
  });

  it("empty, zero and negative totals are ignored", () => {
    const { numbers, onHypotheticalChange } = renderRow(makeAssignment({ points_possible: null }), {
      earned: 5,
      possible: 10,
      curveClassMean: null,
      curveClassSd: null,
    });
    fireEvent.change(numbers[1], { target: { value: "" } });
    fireEvent.change(numbers[1], { target: { value: "0" } });
    fireEvent.change(numbers[1], { target: { value: "-4" } });
    expect(onHypotheticalChange).not.toHaveBeenCalled();
  });
});

describe("AssignmentSliderRow — curve stats", () => {
  it("hidden when the predictor curve is off", () => {
    renderRow(makeAssignment({ curve_class_mean: 0.7 }));
    expect(screen.queryByText("Bell Curve:")).toBeNull();
  });

  it("stored stats become placeholders; no hyp overrides → empty values, Curve Active", () => {
    const { numbers } = renderRow(
      makeAssignment({ curve_class_mean: 0.756, curve_class_sd: 0.104 }),
      undefined,
      { curve: true },
    );
    // [earned, mean, sd] — stored total, so no total input
    expect(numbers).toHaveLength(3);
    expect(numbers[1].placeholder).toBe("76");
    expect(numbers[1].value).toBe("");
    expect(numbers[2].placeholder).toBe("10");
    expect(numbers[2].value).toBe("");
    expect(screen.getByText("Bell Curve:")).toBeTruthy();
    expect(screen.getByText("✓ Curve Active")).toBeTruthy();
  });

  it("no stored stats and no hyp: dash placeholders, no Curve Active", () => {
    const { numbers } = renderRow(makeAssignment(), undefined, { curve: true });
    expect(numbers[1].placeholder).toBe("—");
    expect(numbers[2].placeholder).toBe("—");
    expect(screen.queryByText("✓ Curve Active")).toBeNull();
  });

  it("stored stat of 0 is a real placeholder '0' and activates the curve", () => {
    const { numbers } = renderRow(makeAssignment({ curve_class_sd: 0 }), undefined, { curve: true });
    expect(numbers[2].placeholder).toBe("0");
    expect(screen.getByText("✓ Curve Active")).toBeTruthy();
  });

  it("hyp overrides show as percent values; explicit null overrides suppress stored stats", () => {
    const { numbers, onHypotheticalChange } = renderRow(
      makeAssignment({ curve_class_mean: 0.7, curve_class_sd: 0.1 }),
      { earned: 20, possible: 40, curveClassMean: 0.825, curveClassSd: null },
      { curve: true },
    );
    expect(numbers[1].value).toBe("83");
    expect(numbers[2].value).toBe("");
    expect(screen.getByText("✓ Curve Active")).toBeTruthy();
    fireEvent.change(numbers[0], { target: { value: "21" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 21,
      possible: 40,
      curveClassMean: 0.825,
      curveClassSd: null,
    });
  });

  it("both overrides null with stored stats: no Curve Active", () => {
    renderRow(
      makeAssignment({ curve_class_mean: 0.7, curve_class_sd: 0.1 }),
      { earned: 20, possible: 40, curveClassMean: null, curveClassSd: null },
      { curve: true },
    );
    expect(screen.queryByText("✓ Curve Active")).toBeNull();
  });

  it("mean input: value → fraction, empty → null", () => {
    const { numbers, onHypotheticalChange } = renderRow(
      makeAssignment({ curve_class_mean: 0.7, curve_class_sd: 0.1 }),
      undefined,
      { curve: true },
    );
    fireEvent.change(numbers[1], { target: { value: "65" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 20,
      possible: 40,
      curveClassMean: 0.65,
      curveClassSd: 0.1,
    });
  });

  it("mean input cleared emits null", () => {
    const { numbers, onHypotheticalChange } = renderRow(
      makeAssignment({ curve_class_mean: 0.7 }),
      { earned: 20, possible: 40, curveClassMean: 0.5, curveClassSd: null },
      { curve: true },
    );
    fireEvent.change(numbers[1], { target: { value: "" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 20,
      possible: 40,
      curveClassMean: null,
      curveClassSd: null,
    });
  });

  it("sd input: value → fraction, cleared → null", () => {
    const { numbers, onHypotheticalChange } = renderRow(
      makeAssignment({ curve_class_mean: 0.7, curve_class_sd: 0.1 }),
      { earned: 20, possible: 40, curveClassMean: 0.6, curveClassSd: 0.12 },
      { curve: true },
    );
    fireEvent.change(numbers[2], { target: { value: "8.5" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", {
      earned: 20,
      possible: 40,
      curveClassMean: 0.6,
      curveClassSd: 0.085,
    });
    fireEvent.change(numbers[2], { target: { value: "" } });
    expect(onHypotheticalChange).toHaveBeenLastCalledWith("a1", expect.objectContaining({ curveClassSd: null }));
  });

  it("curve section with no stored total renders [earned, total, mean, sd]", () => {
    const { numbers } = renderRow(makeAssignment({ points_possible: null }), undefined, { curve: true });
    expect(numbers).toHaveLength(4);
    expect(numbers[1].min).toBe("1");
    expect(numbers[2].max).toBe("100");
  });
});

describe("AssignmentSliderRow — DOM snapshot", () => {
  it("curved, no stored total, with hyp", () => {
    const { container } = renderRow(
      makeAssignment({ points_possible: null, curve_class_mean: 0.7 }),
      { earned: 3, possible: 8, curveClassMean: null, curveClassSd: 0.2 },
      { curve: true },
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("raw, stored total, no hyp", () => {
    const { container } = renderRow(makeAssignment());
    expect(container.innerHTML).toMatchSnapshot();
  });
});
