// @vitest-environment jsdom
/**
 * Characterization of AssignmentModal's form contract: the exact draft handed
 * to onSave for create and edit, the numeric parsing of every field (blank →
 * null, 0 stays 0, decimals and negatives pass through, curve percents are
 * stored as fractions), validation (title, total > 0, due date), the bell-curve
 * section, and the save/delete busy + ordering semantics. The Dialog-level
 * smoke tests live in modals.dialog.test.tsx.
 */

import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssignmentModal, type AssignmentDraft } from "./AssignmentModal";
import type { GradeCategory, GradedAssignment } from "@/lib/types";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => ({
    show: vi.fn(),
    dismiss: vi.fn(),
    success: vi.fn(),
    error: toastError,
    info: vi.fn(),
    warn: vi.fn(),
  }),
}));

// Pass the fallback straight through so the tests can pin which copy each
// failure path hands to humanizeError.
const humanizeError = vi.hoisted(() => vi.fn((_err: unknown, fallback: string) => fallback));
vi.mock("@/lib/errorMessage", () => ({ humanizeError }));

const CATEGORIES: GradeCategory[] = [
  { id: "c1", name: "Exams", weight: 0.6, sort_order: 0, drop_lowest: 0 },
  { id: "c2", name: "Homework", weight: 0.4, sort_order: 1, drop_lowest: 0 },
];

const EMPTY: AssignmentDraft = {
  title: "",
  category_id: null,
  points_possible: null,
  points_earned: null,
  due_date: null,
  assignment_type: null,
  notes: null,
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
};

const CURVED: GradedAssignment = {
  id: "a1",
  title: "Midterm",
  course_id: "course-1",
  category_id: "c1",
  points_possible: 100,
  points_earned: 88,
  due_date: "2026-03-14",
  assignment_type: "exam",
  notes: "open book",
  source: "manual",
  curve_class_mean: 0.68,
  curve_class_sd: 0.12,
  curve_avg_target: 0.8,
  curve_sd_delta: 0.1,
};

const PLAIN: GradedAssignment = {
  ...CURVED,
  due_date: null,
  assignment_type: null,
  notes: null,
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
};

// The due-date check parses the date as LOCAL midnight and compares it with the
// UTC ISO date, so east of UTC every real date reads as invalid. These tests
// characterize it in UTC (what CI runs), whatever zone the machine is in.
beforeEach(() => {
  vi.stubEnv("TZ", "UTC");
});

afterEach(() => {
  cleanup();
  toastError.mockClear();
  humanizeError.mockClear();
  vi.unstubAllEnvs();
});

function renderModal(props: Partial<React.ComponentProps<typeof AssignmentModal>> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn<(draft: AssignmentDraft) => Promise<void>>(async () => {});
  const utils = render(
    <AssignmentModal
      open
      categories={CATEGORIES}
      onClose={onClose}
      onSave={onSave}
      {...props}
    />,
  );
  return { ...utils, onClose, onSave };
}

const titleInput = () => screen.getByTestId("gradebook-assignment-title") as HTMLInputElement;
const saveButton = () => screen.getByTestId("gradebook-assignment-save");
const field = (label: string | RegExp) => screen.getByLabelText(label) as HTMLInputElement;
const change = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

describe("AssignmentModal create", () => {
  it("titles the dialog New Assignment with an empty, invalid form", async () => {
    renderModal();
    await screen.findByRole("dialog");
    expect(screen.getByRole("heading", { name: "New Assignment" })).toBeInTheDocument();
    expect(titleInput().value).toBe("");
    expect(field("Earned").value).toBe("");
    expect(field("Total").value).toBe("");
    expect(field("Due Date").value).toBe("");
    expect(field("Notes").value).toBe("");
    expect((screen.getByLabelText("Category") as HTMLSelectElement).value).toBe("");
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toHaveTextContent("Save");
    // Bell curve starts collapsed on create.
    expect(screen.queryByLabelText("Class Average (%)")).toBeNull();
  });

  it("saves the exact all-null draft for a title-only create, then closes", async () => {
    const { onSave, onClose } = renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "Problem Set 5");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toEqual({ ...EMPTY, title: "Problem Set 5" });
    expect(onSave.mock.invocationCallOrder[0]).toBeLessThan(onClose.mock.invocationCallOrder[0]);
  });

  it("does not trim the title in the payload", async () => {
    const { onSave } = renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "  PS 1  ");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].title).toBe("  PS 1  ");
  });

  it("saves every field, with curve percents stored as fractions", async () => {
    const { onSave } = renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "Final");
    change(screen.getByLabelText("Category"), "c2");
    change(field("Earned"), "45.5");
    change(field("Total"), "50");
    change(field("Due Date"), "2026-05-01");
    change(field("Notes"), "cumulative");
    await userEvent.click(screen.getByRole("button", { name: /Bell Curve/ }));
    change(field("Class Average (%)"), "68");
    change(field("Std Dev (%)"), "12");
    change(field("Avg maps to (%)"), "80");
    change(field("Grade per SD (%)"), "10");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({
      title: "Final",
      category_id: "c2",
      points_possible: 50,
      points_earned: 45.5,
      due_date: "2026-05-01",
      assignment_type: null,
      notes: "cumulative",
      curve_class_mean: 68 / 100,
      curve_class_sd: 12 / 100,
      curve_avg_target: 80 / 100,
      curve_sd_delta: 10 / 100,
    });
  });

  it("keeps 0 and negative earned points as numbers, and blank as null", async () => {
    const { onSave } = renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "Quiz");
    change(field("Earned"), "0");
    change(field("Total"), "0.5");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toMatchObject({ points_earned: 0, points_possible: 0.5 });

    change(field("Earned"), "-3");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0]).toMatchObject({ points_earned: -3 });

    change(field("Earned"), "");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(3));
    expect(onSave.mock.calls[2][0]).toMatchObject({ points_earned: null });
  });

  it("maps the Uncategorized option back to null", async () => {
    const { onSave } = renderModal({ initial: PLAIN });
    await screen.findByRole("dialog");
    change(screen.getByLabelText("Category"), "");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0].category_id).toBeNull();
  });

  it("lists categories after Uncategorized", async () => {
    renderModal();
    await screen.findByRole("dialog");
    const options = Array.from(
      (screen.getByLabelText("Category") as HTMLSelectElement).options,
    ).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([["", "Uncategorized"], ["c1", "Exams"], ["c2", "Homework"]]);
  });

  it("has no Delete button on create even with onDelete", async () => {
    renderModal({ onDelete: async () => {} });
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("AssignmentModal validation", () => {
  it("disables Save for blank or whitespace titles", async () => {
    renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "   ");
    expect(saveButton()).toBeDisabled();
    change(titleInput(), "x");
    expect(saveButton()).toBeEnabled();
  });

  it.each([
    ["0", false],
    ["-5", false],
    ["0.01", true],
    ["", true],
  ])("Total %j → Save enabled %s", async (total, enabled) => {
    renderModal();
    await screen.findByRole("dialog");
    change(titleInput(), "x");
    change(field("Total"), total);
    if (enabled) expect(saveButton()).toBeEnabled();
    else expect(saveButton()).toBeDisabled();
  });

  it("shows Required with an error border only after the empty title is blurred", async () => {
    renderModal();
    await screen.findByRole("dialog");
    expect(screen.queryByText("Required")).toBeNull();
    expect(titleInput().style.border).toBe("1px solid var(--border)");
    fireEvent.blur(titleInput());
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(titleInput().style.border).toBe("1px solid var(--err)");
    change(titleInput(), "x");
    expect(screen.queryByText("Required")).toBeNull();
    expect(titleInput().style.border).toBe("1px solid var(--border)");
  });

  it("flags an impossible stored due date and blocks Save", async () => {
    renderModal({ initial: { ...PLAIN, due_date: "2026-02-30" } });
    await screen.findByRole("dialog");
    expect(screen.getByText("Invalid date")).toBeInTheDocument();
    // The error span sits inside the <label>, so its text joins the label's.
    expect(field(/^Due Date/).style.border).toBe("1px solid var(--err)");
    expect(saveButton()).toBeDisabled();
  });

  it("accepts a real due date without the error", async () => {
    renderModal({ initial: { ...PLAIN, due_date: "2024-02-29" } });
    await screen.findByRole("dialog");
    expect(screen.queryByText("Invalid date")).toBeNull();
    expect(field("Due Date").style.border).toBe("1px solid var(--border)");
    expect(saveButton()).toBeEnabled();
  });
});

describe("AssignmentModal edit", () => {
  it("prefills from the assignment and opens the curve section when a mean exists", async () => {
    renderModal({ initial: CURVED });
    await screen.findByRole("dialog");
    expect(screen.getByRole("heading", { name: "Edit Assignment" })).toBeInTheDocument();
    expect(titleInput().value).toBe("Midterm");
    expect((screen.getByLabelText("Category") as HTMLSelectElement).value).toBe("c1");
    expect(field("Earned").value).toBe("88");
    expect(field("Total").value).toBe("100");
    expect(field("Due Date").value).toBe("2026-03-14");
    expect(field("Notes").value).toBe("open book");
    expect(field("Class Average (%)").value).toBe("68.0");
    expect(field("Std Dev (%)").value).toBe("12.0");
    expect(field("Avg maps to (%)").value).toBe("80.0");
    expect(field("Grade per SD (%)").value).toBe("10.0");
    expect(screen.getByRole("button", { name: "Remove curve from this assignment" })).toBeInTheDocument();
  });

  it("saves the unchanged edit draft without id/course_id/source", async () => {
    const { onSave } = renderModal({ initial: CURVED });
    await screen.findByRole("dialog");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toEqual({
      title: "Midterm",
      category_id: "c1",
      points_possible: 100,
      points_earned: 88,
      due_date: "2026-03-14",
      assignment_type: "exam",
      notes: "open book",
      curve_class_mean: 0.68,
      curve_class_sd: 0.12,
      curve_avg_target: 0.8,
      curve_sd_delta: 0.1,
    });
  });

  it("clears blank text fields to null in an edit", async () => {
    const { onSave } = renderModal({ initial: CURVED });
    await screen.findByRole("dialog");
    change(field("Notes"), "");
    change(field("Due Date"), "");
    change(field("Earned"), "");
    change(field("Total"), "");
    change(field("Avg maps to (%)"), "");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({
      notes: null,
      due_date: null,
      points_earned: null,
      points_possible: null,
      curve_avg_target: null,
      curve_class_mean: 0.68,
    });
  });

  it("keeps the curve section closed when only the SD is set", async () => {
    renderModal({ initial: { ...PLAIN, curve_class_sd: 0.1 } });
    await screen.findByRole("dialog");
    expect(screen.queryByLabelText("Std Dev (%)")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Bell Curve/ }));
    expect(field("Std Dev (%)").value).toBe("10.0");
    expect(field("Class Average (%)").value).toBe("");
    expect(screen.getByRole("button", { name: "Remove curve from this assignment" })).toBeInTheDocument();
  });

  it("only offers Remove curve once a mean or SD is entered, and it clears all four fields", async () => {
    const { onSave } = renderModal({ initial: PLAIN });
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: /Bell Curve/ }));
    const remove = () => screen.queryByRole("button", { name: "Remove curve from this assignment" });
    expect(remove()).toBeNull();
    change(field("Avg maps to (%)"), "75");
    expect(remove()).toBeNull();
    change(field("Class Average (%)"), "0");
    expect(field("Class Average (%)").value).toBe("0.0");
    expect(remove()).not.toBeNull();
    change(field("Grade per SD (%)"), "5");
    await userEvent.click(remove()!);
    expect(remove()).toBeNull();
    // The section stays open with every field blank.
    expect(field("Class Average (%)").value).toBe("");
    expect(field("Avg maps to (%)").value).toBe("");
    expect(field("Grade per SD (%)").value).toBe("");
    await userEvent.click(saveButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({
      curve_class_mean: null,
      curve_class_sd: null,
      curve_avg_target: null,
      curve_sd_delta: null,
    });
  });

  it("toggles the curve section and rotates its chevron", async () => {
    renderModal({ initial: CURVED });
    await screen.findByRole("dialog");
    const toggle = screen.getByRole("button", { name: /Bell Curve/ });
    const chevron = toggle.querySelector("span") as HTMLSpanElement;
    expect(chevron.style.transform).toBe("rotate(0deg)");
    await userEvent.click(toggle);
    expect(screen.queryByLabelText("Class Average (%)")).toBeNull();
    expect(chevron.style.transform).toBe("rotate(-90deg)");
    await userEvent.click(toggle);
    expect(field("Class Average (%)").value).toBe("68.0");
  });

  it("resets the form when reopened", async () => {
    const onClose = vi.fn();
    const onSave = vi.fn(async () => {});
    const { rerender } = render(
      <AssignmentModal open initial={CURVED} categories={CATEGORIES} onClose={onClose} onSave={onSave} />,
    );
    await screen.findByRole("dialog");
    change(titleInput(), "");
    fireEvent.blur(titleInput());
    await userEvent.click(screen.getByRole("button", { name: /Bell Curve/ }));
    expect(screen.getByText("Required")).toBeInTheDocument();
    rerender(
      <AssignmentModal open={false} initial={CURVED} categories={CATEGORIES} onClose={onClose} onSave={onSave} />,
    );
    rerender(
      <AssignmentModal open initial={CURVED} categories={CATEGORIES} onClose={onClose} onSave={onSave} />,
    );
    await screen.findByRole("dialog");
    expect(titleInput().value).toBe("Midterm");
    expect(screen.queryByText("Required")).toBeNull();
    expect(field("Class Average (%)").value).toBe("68.0");
  });

  it("re-seeds the draft when the edited assignment changes while open", async () => {
    const onClose = vi.fn();
    const onSave = vi.fn(async () => {});
    const { rerender } = render(
      <AssignmentModal open initial={CURVED} categories={CATEGORIES} onClose={onClose} onSave={onSave} />,
    );
    await screen.findByRole("dialog");
    rerender(
      <AssignmentModal open initial={null} categories={CATEGORIES} onClose={onClose} onSave={onSave} />,
    );
    expect(screen.getByRole("heading", { name: "New Assignment" })).toBeInTheDocument();
    expect(titleInput().value).toBe("");
    expect(screen.queryByLabelText("Class Average (%)")).toBeNull();
  });
});

describe("AssignmentModal busy states", () => {
  it("shows Saving… and disables Save and Delete while onSave is pending", async () => {
    let resolve!: () => void;
    const onSave = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    const { onClose } = renderModal({ initial: PLAIN, onSave, onDelete: async () => {} });
    await screen.findByRole("dialog");
    await userEvent.click(saveButton());
    expect(saveButton()).toHaveTextContent("Saving…");
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(onClose).not.toHaveBeenCalled();
    resolve();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveButton()).toHaveTextContent("Save"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts the humanized save error with the save fallback", async () => {
    const onSave = vi.fn(async () => {
      throw new Error("weird");
    });
    renderModal({ initial: PLAIN, onSave });
    await screen.findByRole("dialog");
    await userEvent.click(saveButton());
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    expect(humanizeError).toHaveBeenCalledWith(
      new Error("weird"),
      "Couldn't save the assignment. Try again.",
    );
    expect(toastError).toHaveBeenCalledWith("Couldn't save the assignment. Try again.");
  });

  it("toasts the humanized delete error with the delete fallback and stays open", async () => {
    const onDelete = vi.fn(async () => {
      throw new Error("gone");
    });
    const { onClose } = renderModal({ initial: PLAIN, onDelete });
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Couldn't delete the assignment. Try again."),
    );
    expect(humanizeError.mock.calls[0][0]).toEqual(new Error("gone"));
    expect(onClose).not.toHaveBeenCalled();
    await waitFor(() => expect(saveButton()).toHaveTextContent("Save"));
    expect(saveButton()).toBeEnabled();
  });

  it("deletes, then closes, disabling both buttons while pending", async () => {
    let resolve!: () => void;
    const onDelete = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    const { onClose, onSave } = renderModal({ initial: PLAIN, onDelete });
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    expect(saveButton()).toHaveTextContent("Saving…");
    resolve();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSave).not.toHaveBeenCalled();
    expect(onDelete.mock.invocationCallOrder[0]).toBeLessThan(onClose.mock.invocationCallOrder[0]);
  });

  it("hides Delete on edit when onDelete is null", async () => {
    renderModal({ initial: PLAIN, onDelete: null });
    await screen.findByRole("dialog");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});
