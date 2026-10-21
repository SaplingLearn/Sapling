// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import * as plans from "@/lib/studyPlanApi";

const query = vi.hoisted(() => ({ value: "" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(query.value) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  getCourses: vi.fn(async () => ({ courses: [{ course_id: "c1", course_code: "BIO101", course_name: "Biology" }] })),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
}));
vi.mock("@/lib/studyPlanApi", () => ({ getStudyPlans: vi.fn(), getStudyPlanSources: vi.fn(), createStudyPlan: vi.fn(), updateStudyPlan: vi.fn(), deleteStudyPlan: vi.fn() }));

beforeEach(() => {
  query.value = "";
  vi.mocked(plans.getStudyPlans).mockResolvedValue({ semester: "Fall 2026", plans: [] });
  vi.mocked(plans.getStudyPlanSources).mockResolvedValue({ documents: [{ id: "d1", file_name: "Undated biology notes.pdf" }], assignments: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("opens one assessment workspace by default, with no separate plan/guide tabs", async () => {
  render(<ToastProvider><Study /></ToastProvider>);
  await screen.findByRole("button", { name: "Create a study plan" });
  expect(screen.getByRole("button", { name: "Study Guide" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: "Study Plans" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Study Guides" })).toBeNull();
  expect(plans.getStudyPlans).toHaveBeenCalledWith("u1", "c1", undefined, expect.any(AbortSignal));
});

it("supports the old plan URL through the same unified assessment setup", async () => {
  query.value = "mode=plan&course=c1";
  render(<ToastProvider><Study /></ToastProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Create a study plan" }));
  await screen.findByLabelText("Assessment date");
  expect(screen.getByLabelText("Undated biology notes.pdf")).toBeEnabled();
  expect(screen.queryByText("Pick an exam…")).toBeNull();
});

it("shows saved history without invoking a separate guide creation flow", async () => {
  render(<ToastProvider><Study /></ToastProvider>);
  await screen.findByRole("button", { name: "Create a study plan" });
  fireEvent.click(await screen.findByRole("button", { name: "Earlier saved guides" }));
  await waitFor(() => expect(screen.getByText("No earlier saved guides for this course and semester.")).toBeTruthy());
  expect(screen.queryByRole("button", { name: "Regenerate" })).toBeNull();
});
