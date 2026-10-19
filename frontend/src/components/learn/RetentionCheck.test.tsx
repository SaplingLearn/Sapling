// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
const api = vi.hoisted(() => ({ startRetentionCheck: vi.fn(), answerRetentionCheck: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), ...api }));
import { ApiError } from "@/lib/api";
import { RetentionCheck } from "./RetentionCheck";
const courses = [{ course_id: "c1", course_name: "Computer Science" }, { course_id: "c2", course_name: "Mathematics" }] as EnrolledCourse[];
const item = { node_id: "n1", question_hash: "qh", format: "free", difficulty: 1, prompt: "What do you remember?" };
beforeEach(() => { vi.resetAllMocks(); });
afterEach(cleanup);
async function open() { fireEvent.click(screen.getByTestId("retention-open")); await screen.findByTestId("retention-item"); }

it("never creates a pose on mount/course change and honestly renders no eligible items", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [] });
  render(<RetentionCheck userId="u1" courses={courses} initialCourseId="c2" />);
  expect(api.startRetentionCheck).not.toHaveBeenCalled();
  expect((screen.getByTestId("retention-course") as HTMLSelectElement).value).toBe("c2");
  fireEvent.change(screen.getByTestId("retention-course"), { target: { value: "c1" } });
  expect(api.startRetentionCheck).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("retention-open"));
  expect(await screen.findByTestId("retention-empty")).toBeTruthy();
  expect(api.startRetentionCheck).toHaveBeenCalledWith("u1", "c1");
  expect(screen.getByTestId("retention-empty").textContent).toContain("eligible unseen");
});

it("ignores a response from the course the learner left", async () => {
  let finish!: (value: { items: typeof item[] }) => void;
  api.startRetentionCheck.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  render(<RetentionCheck userId="u1" courses={courses} />);
  fireEvent.click(screen.getByTestId("retention-open"));
  fireEvent.change(screen.getByTestId("retention-course"), { target: { value: "c2" } });
  await act(async () => { finish({ items: [item] }); });
  expect(screen.queryByTestId("retention-item")).toBeNull();
  expect((screen.getByTestId("retention-course") as HTMLSelectElement).value).toBe("c2");
  expect(api.startRetentionCheck).toHaveBeenCalledTimes(1);
});

it("grades only the explicitly submitted item and does not infer mastery", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "My own remembered explanation" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  expect(await screen.findByTestId("retention-result")).toBeTruthy();
  expect(api.answerRetentionCheck).toHaveBeenCalledWith({ user_id: "u1", node_id: "n1", question_hash: "qh", answer: "My own remembered explanation", idk: false });
  expect(screen.getByTestId("retention-result").textContent).toContain("not proof of mastery");
  expect(screen.queryByTestId("retention-answer")).toBeNull();
  fireEvent.click(screen.getByTestId("retention-next"));
  expect(screen.getByTestId("retention-finished")).toBeTruthy();
});

it("sends stored option letters/reason, and honest unknown sends no answer", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [{ ...item, format: "mc_reason", options: [{ letter: "A", text: "First" }, { letter: "B", text: "Second" }] }, { ...item, question_hash: "next" }] });
  api.answerRetentionCheck.mockResolvedValue({ correct: false, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.click(screen.getByRole("radio", { name: "B. Second" }));
  expect((screen.getByTestId("retention-submit") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByTestId("retention-reason"), { target: { value: "   " } });
  expect((screen.getByTestId("retention-submit") as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByTestId("retention-idk") as HTMLButtonElement).disabled).toBe(false);
  fireEvent.change(screen.getByTestId("retention-reason"), { target: { value: "My reasoning" } });
  fireEvent.click(screen.getByTestId("retention-submit")); await screen.findByTestId("retention-result");
  expect(api.answerRetentionCheck).toHaveBeenLastCalledWith({ user_id: "u1", node_id: "n1", question_hash: "qh", selected_option: "B", reason: "My reasoning", idk: false });
  fireEvent.click(screen.getByTestId("retention-next")); fireEvent.click(screen.getByTestId("retention-idk"));
  await waitFor(() => expect(api.answerRetentionCheck).toHaveBeenLastCalledWith({ user_id: "u1", node_id: "n1", question_hash: "next", idk: true }));
});

it("preserves an ungraded answer on refusal/outage and requires an explicit retry", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockResolvedValueOnce({ graded: false, refused: true }).mockRejectedValueOnce(new ApiError("unavailable", 503));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "My attempt" } });
  fireEvent.click(screen.getByTestId("retention-submit")); await screen.findByRole("alert");
  expect(screen.queryByTestId("retention-result")).toBeNull();
  expect((screen.getByTestId("retention-answer") as HTMLTextAreaElement).value).toBe("My attempt");
  fireEvent.click(screen.getByTestId("retention-submit"));
  await waitFor(() => expect(api.answerRetentionCheck).toHaveBeenCalledTimes(2));
  await waitFor(() => expect((screen.getByTestId("retention-submit") as HTMLButtonElement).disabled).toBe(false));
  expect((screen.getByTestId("retention-answer") as HTMLTextAreaElement).value).toBe("My attempt");
  expect(screen.queryByTestId("retention-result")).toBeNull();
});

it("does not silently reopen an expired/already-graded pose", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockRejectedValue(new ApiError("not a post-test item", 409));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.click(screen.getByTestId("retention-idk"));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByTestId("retention-item")).toBeNull();
  expect(api.startRetentionCheck).toHaveBeenCalledTimes(1);
});
