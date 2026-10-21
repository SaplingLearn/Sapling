// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StudyPlanPanel } from "./StudyPlanPanel";
import * as api from "@/lib/studyPlanApi";
import { ApiError } from "@/lib/api";

vi.mock("@/lib/studyPlanApi", () => ({
  getStudyPlans: vi.fn(), getStudyPlanSources: vi.fn(), createStudyPlan: vi.fn(),
  updateStudyPlan: vi.fn(), deleteStudyPlan: vi.fn(),
}));

const topicId = "a".repeat(32);
const fixture = (): api.StudyPlan => ({
  id: "plan", version: 1, title: "Biology midterm", assessment_type: "exam", assessment_date: "2027-01-30",
  start_date: "2027-01-21", timezone: "America/New_York", coverage: "Cells", document_ids: [], assignment_ids: [],
  study_days: [0, 1, 2, 3, 4, 5, 6], minutes_per_day: 60, mastered_count: 0, warnings: [],
  guide_overview: "Connect cell structure to its function before reviewing transport.",
  sources: [{ id: "assessment-coverage", label: "Your assessment coverage" }],
  topics: [{ id: topicId, name: "Cells", description: "Cell structure", parent_id: null,
    prerequisite_ids: [], source_ids: ["assessment-coverage"], importance: .8,
    checked: false, status: "in_progress", mastery_score: .5, node_id: "node", study_points: ["Explain the role of each organelle."] }],
  sessions: [{ id: "session", topic_id: topicId, kind: "study", scheduled_date: "2027-01-22", minutes: 25, completed: false }],
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getStudyPlans).mockResolvedValue({ semester: "Fall 2026", plans: [fixture()] });
  vi.mocked(api.getStudyPlanSources).mockResolvedValue({ documents: [{ id: "doc", file_name: "Lecture.pdf" }], assignments: [] });
});
afterEach(cleanup);

function open() { fireEvent.click(screen.getByRole("button", { name: "Study guide" })); }

describe("Assessment study plan", () => {
  it("loads lazily and derives topic progress separately from session completion", async () => {
    render(<StudyPlanPanel userId="u" courseId="c" semester="Fall 2026" />);
    expect(api.getStudyPlans).not.toHaveBeenCalled();
    open();
    await screen.findByText("0 of 1 mastered");
    expect(screen.getByText("Connect cell structure to its function before reviewing transport.")).toBeTruthy();
    expect(screen.getByText("Explain the role of each organelle.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Your study schedule" })).toBeTruthy();
    expect(api.getStudyPlans).toHaveBeenCalledWith("u", "c", "Fall 2026", expect.any(AbortSignal));
    expect(screen.getByRole("progressbar", { name: "Cells mastery" })).toHaveAttribute("value", "0.5");
    const completed = fixture();
    completed.version = 2;
    completed.sessions[0].completed = true;
    vi.mocked(api.updateStudyPlan).mockResolvedValue(completed);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeChecked());
    expect(screen.getByText("0 of 1 mastered")).toBeTruthy();
    expect(api.updateStudyPlan).toHaveBeenCalledWith("u", "c", expect.objectContaining({ version: 1 }),
      { session: { id: "session", completed: true } }, "Fall 2026", expect.any(AbortSignal));
  });

  it("creates a plan from assessment details and selected library material", async () => {
    vi.mocked(api.getStudyPlans).mockResolvedValue({ semester: "Fall 2026", plans: [] });
    vi.mocked(api.createStudyPlan).mockResolvedValue(fixture());
    render(<StudyPlanPanel userId="u" courseId="c" />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Create a study plan" }));
    fireEvent.change(screen.getByLabelText("Assessment name"), { target: { value: "Biology midterm" } });
    fireEvent.change(screen.getByLabelText("Assessment date"), { target: { value: "2027-01-30" } });
    fireEvent.click(screen.getByLabelText("Lecture.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Generate study plan" }));
    await screen.findByText("0 of 1 mastered");
    expect(api.createStudyPlan).toHaveBeenCalledWith("u", "c", expect.objectContaining({
      title: "Biology midterm", assessment_date: "2027-01-30", document_ids: ["doc"],
    }), undefined, expect.any(AbortSignal));
  });

  it("allows an undated exam and undated material with a manually entered date", async () => {
    vi.mocked(api.getStudyPlanSources).mockResolvedValue({ documents: [{ id: "doc", file_name: "Undated notes.pdf" }],
      assignments: [{ id: "exam", title: "Midterm", due_date: null, assignment_type: "exam" }] });
    vi.mocked(api.createStudyPlan).mockResolvedValue(fixture());
    render(<StudyPlanPanel userId="u" courseId="c" expanded />);
    fireEvent.click(await screen.findByRole("button", { name: "New assessment" }));
    fireEvent.change(screen.getByLabelText("Existing quiz or exam (optional)"), { target: { value: "exam" } });
    expect(screen.getByLabelText("Assessment name")).toHaveValue("Midterm");
    expect(screen.getByLabelText("Assessment date")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Assessment date"), { target: { value: "2027-01-30" } });
    fireEvent.click(screen.getByLabelText("Undated notes.pdf"));
    fireEvent.click(screen.getByRole("button", { name: "Generate study plan" }));
    await waitFor(() => expect(api.createStudyPlan).toHaveBeenCalledOnce());
    expect(api.createStudyPlan).toHaveBeenCalledWith("u", "c", expect.objectContaining({
      assessment_date: "2027-01-30", assignment_ids: ["exam"], document_ids: ["doc"],
    }), undefined, expect.any(AbortSignal));
  });

  it("opens a library material directly in a new assessment without needing a dated assignment", async () => {
    render(<StudyPlanPanel userId="u" courseId="c" expanded initialDocumentId="doc" />);
    await screen.findByLabelText("Assessment date");
    expect(screen.getByLabelText("Lecture.pdf")).toBeChecked();
    expect(screen.getByLabelText("Assessment date")).toHaveValue("");
  });

  it("edits topics without sending derived mastery fields and can reschedule sessions", async () => {
    vi.mocked(api.updateStudyPlan).mockResolvedValue(fixture());
    render(<StudyPlanPanel userId="u" courseId="c" />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Edit topics" }));
    fireEvent.change(screen.getByLabelText("Topic name"), { target: { value: "Cell membranes" } });
    fireEvent.click(screen.getByRole("button", { name: "Save topics and replan" }));
    await waitFor(() => expect(api.updateStudyPlan).toHaveBeenCalledOnce());
    const changes = vi.mocked(api.updateStudyPlan).mock.calls[0][3];
    expect(changes.topics?.[0].name).toBe("Cell membranes");
    expect(changes.topics?.[0].study_points).toEqual(["Explain the role of each organelle."]);
    expect(changes.topics?.[0]).not.toHaveProperty("mastery_score");
    await waitFor(() => expect(screen.getByLabelText("Move study: Cells")).not.toBeDisabled());
    fireEvent.change(screen.getByLabelText("Move study: Cells"), { target: { value: "2027-01-23" } });
    await waitFor(() => expect(api.updateStudyPlan).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.updateStudyPlan).mock.calls[1][3]).toEqual({ session: { id: "session", scheduled_date: "2027-01-23" } });
  });

  it("retains the current plan when a stale write fails and offers a refresh", async () => {
    vi.mocked(api.updateStudyPlan).mockRejectedValue(new ApiError("conflict", 409));
    render(<StudyPlanPanel userId="u" courseId="c" />);
    open();
    await screen.findByText("0 of 1 mastered");
    fireEvent.click(screen.getByRole("checkbox"));
    await screen.findByRole("alert");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Refresh progress" }));
    await waitFor(() => expect(api.getStudyPlans).toHaveBeenCalledTimes(2));
  });

  it("ignores a delayed response from another course", async () => {
    let resolve!: (value: { semester: string; plans: api.StudyPlan[] }) => void;
    vi.mocked(api.getStudyPlans).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const view = render(<StudyPlanPanel userId="u" courseId="old" />);
    open();
    const next = fixture();
    next.topics[0].name = "Calculus";
    vi.mocked(api.getStudyPlans).mockResolvedValue({ semester: "Fall 2026", plans: [next] });
    view.rerender(<StudyPlanPanel userId="u" courseId="new" />);
    await screen.findByRole("progressbar", { name: "Calculus mastery" });
    resolve({ semester: "old", plans: [fixture()] });
    await waitFor(() => expect(screen.queryByRole("progressbar", { name: "Cells mastery" })).toBeNull());
  });
});
