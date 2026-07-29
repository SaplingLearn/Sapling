// @vitest-environment jsdom
/**
 * Smoke coverage for the four Gradebook modals migrated onto the shared
 * `Dialog` (#109). They had no tests, and the migration is invisible to tsc:
 * a modal that silently stops opening, loses its submit handler, or drops the
 * accessible dialog role still typechecks perfectly.
 *
 * Two layers of contract are asserted:
 *
 * 1. Dialog semantics every consumer depends on (#109) — closed renders
 *    nothing, open renders a labelled dialog with its controls wired.
 * 2. Failure surfacing (#166) — a rejected onSave/onDelete keeps the modal
 *    OPEN, re-enables its button, and toasts the error instead of silently
 *    looking like a dead button (the modals catch; the parent callbacks in
 *    screens/Gradebook/Course.tsx deliberately don't).
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssignmentModal } from "./AssignmentModal";
import { EditWeightsModal } from "./EditWeightsModal";
import { LetterScaleEditor } from "./LetterScaleEditor";
import type { GradeCategory, GradedAssignment } from "@/lib/types";

// The modals toast their own save/delete failures (#166); render them without
// the real ToastProvider and capture what they'd have shown the user.
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

const CATEGORIES: GradeCategory[] = [
  { id: "c1", name: "Exams", weight: 0.6, sort_order: 0, drop_lowest: 0 },
  { id: "c2", name: "Homework", weight: 0.4, sort_order: 1, drop_lowest: 0 },
];

// EditWeightsModal only enables Save when weights sum to 100.
const WEIGHT_CATEGORIES: GradeCategory[] = [
  { id: "c1", name: "Exams", weight: 60, sort_order: 0, drop_lowest: 0 },
  { id: "c2", name: "Homework", weight: 40, sort_order: 1, drop_lowest: 0 },
];

// Prefilled edit target: gives AssignmentModal a valid draft (Save enabled)
// and a Delete button without form interaction.
const ASSIGNMENT: GradedAssignment = {
  id: "a1",
  title: "Midterm",
  course_id: "course-1",
  category_id: "c1",
  points_possible: 100,
  points_earned: 88,
  due_date: null,
  assignment_type: null,
  notes: null,
  source: "manual",
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
};

afterEach(() => {
  cleanup();
  toastError.mockClear();
});

describe("Gradebook modals on the shared Dialog", () => {
  it("render nothing at all while closed", () => {
    const noop = () => {};
    const save = async () => {};

    render(
      <>
        <AssignmentModal open={false} categories={CATEGORIES} onClose={noop} onSave={save} />
        <EditWeightsModal open={false} initial={CATEGORIES} onClose={noop} onSave={save} />
        <LetterScaleEditor open={false} initial={null} onClose={noop} onSave={save} />
      </>,
    );

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    [
      "New Assignment",
      (onClose: () => void) => (
        <AssignmentModal open categories={CATEGORIES} onClose={onClose} onSave={async () => {}} />
      ),
    ],
    [
      "Edit categories & weights",
      (onClose: () => void) => (
        <EditWeightsModal open initial={CATEGORIES} onClose={onClose} onSave={async () => {}} />
      ),
    ],
    [
      "Letter scale",
      (onClose: () => void) => (
        <LetterScaleEditor open initial={null} onClose={onClose} onSave={async () => {}} />
      ),
    ],
  ])("%s opens as a labelled dialog and closes on Escape", async (title, renderModal) => {
    const onClose = vi.fn();
    render(renderModal(onClose));

    const dialog = await screen.findByRole("dialog");
    // aria-labelledby must resolve to the visible heading, or screen readers
    // announce an unnamed dialog.
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(dialog.getAttribute("aria-labelledby")).toBe(
      screen.getByRole("heading", { name: title }).id,
    );

    // Dialog moves focus on a 20ms timer. Escape is only meaningful once focus
    // is inside the panel — pressed before that it lands on <body> and never
    // reaches the handler, which is a test artifact rather than a real bug.
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("puts initial focus on the assignment title, not the close button", async () => {
    render(
      <AssignmentModal open categories={CATEGORIES} onClose={() => {}} onSave={async () => {}} />,
    );

    // The regression this guards: Dialog focuses the first focusable node,
    // and its close button precedes {children} in the DOM — so without
    // initialFocusRef a form dialog opens with focus on "Close".
    await waitFor(() => {
      const active = document.activeElement as HTMLElement | null;
      expect(active?.getAttribute("aria-label")).not.toBe("Close dialog");
      expect(active?.tagName).toBe("INPUT");
    });
  });

  it("keeps Cancel wired to onClose", async () => {
    const onClose = vi.fn();
    render(
      <AssignmentModal open categories={CATEGORIES} onClose={onClose} onSave={async () => {}} />,
    );

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  // #166 — a failed save must not look like a successful one (or a dead
  // button): the dialog stays open, Save comes back, and a toast says why.
  it.each([
    [
      "AssignmentModal",
      (onClose: () => void, onSave: () => Promise<void>) => (
        <AssignmentModal
          open
          initial={ASSIGNMENT}
          categories={CATEGORIES}
          onClose={onClose}
          onSave={onSave}
        />
      ),
    ],
    [
      "EditWeightsModal",
      (onClose: () => void, onSave: () => Promise<void>) => (
        <EditWeightsModal open initial={WEIGHT_CATEGORIES} onClose={onClose} onSave={onSave} />
      ),
    ],
    [
      "LetterScaleEditor",
      (onClose: () => void, onSave: () => Promise<void>) => (
        <LetterScaleEditor open initial={null} onClose={onClose} onSave={onSave} />
      ),
    ],
  ])("%s stays open, re-enables Save, and toasts when onSave rejects", async (_name, renderModal) => {
    const onClose = vi.fn();
    const onSave = vi.fn(async () => {
      throw new Error("HTTP 500: boom");
    });
    render(renderModal(onClose, onSave));

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // "Saving…" must give way to an enabled "Save" again so the user can retry.
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
  });

  it("LetterScaleEditor's Reset to default toasts on failure and stays usable", async () => {
    // Reset is the third #166 swallow in this file's modals: a bare floating
    // onSave(null) used to reject invisibly. On failure the dialog stays
    // open, the toast says why, and the button re-enables.
    const onSave = vi.fn(async () => {
      throw new Error("HTTP 500: boom");
    });
    render(<LetterScaleEditor open initial={null} onClose={() => {}} onSave={onSave} />);

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledWith(null));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reset to default" })).toBeEnabled(),
    );
  });

  it("keeps AssignmentModal open and toasts when onDelete rejects", async () => {
    const onClose = vi.fn();
    const onDelete = vi.fn(async () => {
      throw new Error("HTTP 500: boom");
    });
    render(
      <AssignmentModal
        open
        initial={ASSIGNMENT}
        categories={CATEGORIES}
        onClose={onClose}
        onSave={async () => {}}
        onDelete={onDelete}
      />,
    );

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(onDelete).toHaveBeenCalled());
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled());
  });
});
