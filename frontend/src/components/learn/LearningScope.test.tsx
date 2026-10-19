// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DiagnosisSummary, GoalEditor } from "./LearningScope";
import type { GraphNode } from "@/lib/data";
import type { LoopDiagnosisSkill } from "@/lib/api";

afterEach(cleanup);

it("requires confirmation and keeps the thirteenth target out until one is removed", () => {
  const save = vi.fn();
  const nodes = Array.from({ length: 13 }, (_, i) => ({ id: `n${i}`, name: `Concept ${i}`, course_id: "c1" } as GraphNode));
  render(<GoalEditor goal={null} nodes={nodes} busy={false} error={null} onSave={save} onCancel={vi.fn()} />);
  for (let i = 0; i < 12; i++) fireEvent.click(screen.getByRole("checkbox", { name: `Concept ${i}` }));
  expect((screen.getByRole("checkbox", { name: "Concept 12" }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Concept 0" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Concept 12" }));
  fireEvent.click(screen.getByRole("button", { name: "Use this scope" }));
  expect(save.mock.calls[0][0].target_node_ids).toHaveLength(12);
  expect(save.mock.calls[0][0].target_node_ids).not.toContain("n0");
  expect(save.mock.calls[0][0].target_node_ids).toContain("n12");
});

it("does not turn range, contradictory, or untested evidence into mastery claims", () => {
  const statuses: LoopDiagnosisSkill['status'][] = ["bracketed", "partial", "above_range", "below_range", "untested", "inconsistent"];
  render(<DiagnosisSummary names={new Map(statuses.map((value) => [value, value]))} diagnosis={{
    status: "limited", stop_reason: "coverage_limit", skills: statuses.map((value) => ({
      node_id: value, status: value, floor_difficulty: null, ceiling_difficulty: null, independent_correct: 0, independent_incorrect: 0,
      independent_observations: 0, observations: 2, tested_difficulties: [], available_difficulties: [1, 2, 3], contradictory_difficulties: [],
    })),
  }} />);
  fireEvent.click(screen.getByText("Evidence by concept (6)"));
  expect(screen.getByTestId("loop-diagnosis-untested").textContent).toContain("Not assessed");
  expect(screen.getByTestId("loop-diagnosis-inconsistent").textContent).toContain("Mixed evidence");
  expect(screen.getByTestId("loop-diagnosis-above_range").textContent).toContain("upper limit was not found");
  expect(screen.getByTestId("loop-diagnosis-below_range").textContent).toContain("independent success level was not found");
  expect(screen.getByTestId("loop-diagnosis").textContent).toContain("could not bound every concept");
});

it("offers whole-course and Library recovery when the course has no concepts", () => {
  const save = vi.fn();
  render(<GoalEditor goal={null} nodes={[]} busy={false} error={null} onSave={save} onCancel={vi.fn()} />);
  const empty = screen.getByTestId("loop-goal-no-concepts");
  expect(empty.querySelector('a[href="/library"]')).toBeTruthy();
  expect((screen.getByRole("button", { name: "Use this scope" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Explore the whole course instead" }));
  expect((screen.getByRole("radio", { name: "Explore the whole course" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Use this scope" }));
  expect(save).toHaveBeenCalledWith(null);
});

it("keeps the objective draft and selections when a save fails, and while concepts reload", () => {
  const nodes = [{ id: "n1", name: "Recursion", course_id: "c1" } as GraphNode];
  const { rerender } = render(<GoalEditor goal={null} nodes={nodes} busy={false} error={null} onSave={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByRole("textbox", { name: /Your objective/ }), { target: { value: "Trace recursion by hand" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Recursion" }));
  rerender(<GoalEditor goal={null} nodes={nodes} busy={false} error="Couldn't update your learning scope." onSave={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByRole("alert").textContent).toContain("Your draft is kept.");
  expect((screen.getByRole("textbox", { name: /Your objective/ }) as HTMLTextAreaElement).value).toBe("Trace recursion by hand");
  expect((screen.getByRole("checkbox", { name: "Recursion" }) as HTMLInputElement).checked).toBe(true);
  const retry = vi.fn();
  rerender(<GoalEditor goal={null} nodes={nodes} busy={false} error={null} nodesError onRetryNodes={retry} onSave={vi.fn()} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByTestId("loop-goal-retry-concepts"));
  expect(retry).toHaveBeenCalled();
  expect((screen.getByRole("textbox", { name: /Your objective/ }) as HTMLTextAreaElement).value).toBe("Trace recursion by hand");
});
