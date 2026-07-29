// @vitest-environment jsdom
/**
 * CurveSettingsModal failure surfacing (#166) — the fourth gradebook modal
 * with the same swallowed-save shape, private to Course.tsx (exported for
 * this test only). A rejected onSave must keep the dialog open, re-enable
 * Save, and toast the error; success closes. Course.tsx's screen-level
 * concerns (data loading, tables, charts) are out of scope here, so every
 * heavy sibling import is stubbed — this file exists to pin the modal's
 * error contract, nothing else.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/api", () => ({
  getGradebookCourse: vi.fn(),
  bulkUpdateCategories: vi.fn(),
  deleteCategory: vi.fn(),
  createGradedAssignment: vi.fn(),
  updateGradedAssignment: vi.fn(),
  deleteGradedAssignment: vi.fn(),
  setLetterScale: vi.fn(),
  getGradescopeStatus: vi.fn(),
  listGradescopeLinks: vi.fn(),
  syncGradescopeCourse: vi.fn(),
  setCurveSettings: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/Gradebook/AssignmentList", () => ({ AssignmentList: () => null }));
vi.mock("@/components/Gradebook/GradescopeSyncModal", () => ({ GradescopeSyncModal: () => null }));
vi.mock("@/components/Gradebook/GradePredictorPanel", () => ({ GradePredictorPanel: () => null }));
vi.mock("@/components/Gradebook/AmbientOrbs", () => ({ AmbientOrbs: () => null }));

import { CurveSettingsModal } from "./Course";
import type { GradebookCourse } from "@/lib/types";

const COURSE = {
  curve_avg_target: null,
  curve_sd_delta: null,
} as GradebookCourse;

afterEach(() => {
  cleanup();
  toastError.mockClear();
});

describe("CurveSettingsModal failure surfacing (#166)", () => {
  it("stays open, re-enables Save, and toasts when onSave rejects", async () => {
    const onClose = vi.fn();
    const onSave = vi.fn(async () => {
      throw new Error("HTTP 500: boom");
    });
    render(<CurveSettingsModal open course={COURSE} onClose={onClose} onSave={onSave} />);

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
  });

  it("closes on a successful save (control)", async () => {
    const onClose = vi.fn();
    render(
      <CurveSettingsModal open course={COURSE} onClose={onClose} onSave={async () => {}} />,
    );

    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toastError).not.toHaveBeenCalled();
  });
});
