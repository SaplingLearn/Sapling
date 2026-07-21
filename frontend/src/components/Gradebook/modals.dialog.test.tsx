// @vitest-environment jsdom
/**
 * Smoke coverage for the four Gradebook modals migrated onto the shared
 * `Dialog` (#109). They had no tests, and the migration is invisible to tsc:
 * a modal that silently stops opening, loses its submit handler, or drops the
 * accessible dialog role still typechecks perfectly.
 *
 * These assert the contract every consumer depends on — closed renders
 * nothing, open renders a labelled dialog with its controls wired — rather
 * than the internals of each form.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssignmentModal } from "./AssignmentModal";
import { EditWeightsModal } from "./EditWeightsModal";
import { LetterScaleEditor } from "./LetterScaleEditor";
import type { GradeCategory } from "@/lib/types";

const CATEGORIES: GradeCategory[] = [
  { id: "c1", name: "Exams", weight: 0.6, sort_order: 0, drop_lowest: 0 },
  { id: "c2", name: "Homework", weight: 0.4, sort_order: 1, drop_lowest: 0 },
];

afterEach(cleanup);

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
});
