// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TopicChecklistPanel } from "./TopicChecklistPanel";
import { getTopicChecklist, refreshTopicChecklist, setTopicReviewed, type TopicChecklist } from "@/lib/topicChecklistApi";

vi.mock("@/lib/topicChecklistApi", () => ({
  getTopicChecklist: vi.fn(), refreshTopicChecklist: vi.fn(), setTopicReviewed: vi.fn(),
}));

const fixture = (): TopicChecklist => ({
  course_id: "cs", semester: "Fall 2026", generated_at: "2026-10-12", needs_refresh: false,
  assessments: [], warnings: [], review_after_days: 7,
  topics: [{ id: "recursion", name: "Recursion", description: "Base cases and recursive calls.",
    importance: 0.9, parent_id: null, prerequisite_ids: [], prerequisite_gaps: [],
    status: "needs_review", checked: false, mastery_score: 0.3, last_studied_at: null,
    review_reasons: ["Weak mastery"], priority: "high", assessments: [],
    sources: [{ id: "catalog", label: "BU catalog" }], node_id: "n" }],
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getTopicChecklist).mockResolvedValue(fixture());
  vi.mocked(refreshTopicChecklist).mockResolvedValue(fixture());
  vi.mocked(setTopicReviewed).mockResolvedValue(fixture());
});
afterEach(cleanup);

function open() {
  fireEvent.click(screen.getByRole("button", { name: "Topic checklist" }));
}

describe("Topic checklist integration", () => {
  it("loads on opening, scopes by semester, and avoids unnecessary generation", async () => {
    render(<TopicChecklistPanel userId="u" courseId="cs" semester="Fall 2026" />);
    expect(getTopicChecklist).not.toHaveBeenCalled();
    open();
    await screen.findByRole("checkbox", { name: "Studied Recursion" });
    expect(getTopicChecklist).toHaveBeenCalledWith("u", "cs", "Fall 2026", expect.any(AbortSignal));
    expect(refreshTopicChecklist).not.toHaveBeenCalled();
    expect(screen.getByText("Weak mastery")).toBeTruthy();
    expect(screen.getByText("Sources: BU catalog")).toBeTruthy();
  });

  it("refreshes changed evidence automatically and filters weak topics", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ ...fixture(), needs_refresh: true });
    render(<TopicChecklistPanel userId="u" courseId="cs" />);
    open();
    await waitFor(() => expect(refreshTopicChecklist).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    fireEvent.change(screen.getByLabelText("Filter checklist topics"), { target: { value: "not_started" } });
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("No topics match this view.")).toBeTruthy();
  });

  it("persists checks and displays the server's mastery status", async () => {
    const checked = fixture();
    checked.topics[0].checked = true;
    vi.mocked(setTopicReviewed).mockResolvedValue(checked);
    render(<TopicChecklistPanel userId="u" courseId="cs" semester="Spring 2026" />);
    open();
    const checkbox = await screen.findByRole("checkbox", { name: "Studied Recursion" });
    await waitFor(() => expect(checkbox).not.toBeDisabled());
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(setTopicReviewed).toHaveBeenCalledWith("u", "cs", "recursion", true, "Spring 2026", expect.any(AbortSignal));
    expect(screen.getByText("Needs review · Prioritize")).toBeTruthy();
  });

  it("keeps freshness from the last read when a check returns only topic state", async () => {
    // A checkmark never changes evidence, so PATCH omits needs_refresh/warnings
    // rather than re-reading every source; the panel keeps what it had.
    vi.mocked(getTopicChecklist).mockResolvedValue({ ...fixture(), warnings: ["Some source text was limited."] });
    const topicState: Partial<TopicChecklist> = fixture();
    delete topicState.needs_refresh;
    delete topicState.warnings;
    topicState.topics![0].checked = true;
    vi.mocked(setTopicReviewed).mockResolvedValue(topicState as TopicChecklist);
    render(<TopicChecklistPanel userId="u" courseId="cs" />);
    open();
    const checkbox = await screen.findByRole("checkbox", { name: "Studied Recursion" });
    await waitFor(() => expect(checkbox).not.toBeDisabled());
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(screen.getByText("Some source text was limited.")).toBeTruthy();
  });

  it("keeps the last outline when generation fails and allows retry", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ ...fixture(), needs_refresh: true });
    vi.mocked(refreshTopicChecklist).mockRejectedValueOnce(new Error("503"));
    render(<TopicChecklistPanel userId="u" courseId="cs" />);
    open();
    await screen.findByRole("alert");
    expect(screen.getByRole("checkbox", { name: "Studied Recursion" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update from materials" }));
    await waitFor(() => expect(refreshTopicChecklist).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("does not display another course's delayed response", async () => {
    let resolve!: (value: TopicChecklist) => void;
    vi.mocked(getTopicChecklist).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const view = render(<TopicChecklistPanel userId="u" courseId="old" />);
    open();
    const next = fixture();
    next.topics[0].name = "Calculus";
    vi.mocked(getTopicChecklist).mockResolvedValue(next);
    view.rerender(<TopicChecklistPanel userId="u" courseId="new" />);
    await screen.findByRole("checkbox", { name: "Studied Calculus" });
    resolve(fixture());
    await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Studied Recursion" })).toBeNull());
  });

  it("switches a retaken course's semester for reads and writes", async () => {
    render(<TopicChecklistPanel userId="u" courseId="cs" semesters={["Fall 2026", "Spring 2026"]} />);
    open();
    await screen.findByRole("checkbox");
    fireEvent.change(screen.getByLabelText("Checklist semester"), { target: { value: "Spring 2026" } });
    await waitFor(() => expect(getTopicChecklist).toHaveBeenLastCalledWith("u", "cs", "Spring 2026", expect.any(AbortSignal)));
    await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(setTopicReviewed).toHaveBeenCalledWith("u", "cs", "recursion", true, "Spring 2026", expect.any(AbortSignal)));
  });

  it("keeps a failed check unchecked and aborts requests on unmount", async () => {
    vi.mocked(setTopicReviewed).mockRejectedValue(new Error("500"));
    const view = render(<TopicChecklistPanel userId="u" courseId="cs" />);
    open();
    const checkbox = await screen.findByRole("checkbox");
    await waitFor(() => expect(checkbox).not.toBeDisabled());
    fireEvent.click(checkbox);
    await screen.findByRole("alert");
    expect(checkbox).not.toBeChecked();
    const signal = vi.mocked(setTopicReviewed).mock.calls[0][5];
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
