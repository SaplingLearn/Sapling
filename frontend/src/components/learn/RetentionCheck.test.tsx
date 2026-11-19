// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { EnrolledCourse } from "@/lib/api";
const api = vi.hoisted(() => ({ startRetentionCheck: vi.fn(), answerRetentionCheck: vi.fn(), markRetentionShown: vi.fn() }));
/** Spec §13 A126: what an answer reports beside itself when the page stayed visible. */
const VISIBLE = { hidden_count: 0, hidden_s: 0 };
vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), ...api }));
import { ApiError } from "@/lib/api";
import { __resetFeedbackPacingForTests, feedbackHeld } from "@/lib/feedbackPacing";
import { RetentionCheck } from "./RetentionCheck";
import crisisFixture from "@/test-utils/crisisSupport.json";
const courses = [{ course_id: "c1", course_name: "Computer Science" }, { course_id: "c2", course_name: "Mathematics" }] as EnrolledCourse[];
const item = { node_id: "n1", question_hash: "qh", format: "free", difficulty: 1, prompt: "What do you remember?" };
beforeEach(() => { vi.resetAllMocks(); });
afterEach(cleanup);
async function open() { fireEvent.click(screen.getByTestId("retention-open")); await screen.findByTestId("retention-item"); }

it("holds the shell's feedback prompts only while an opened check is in progress (lib/feedbackPacing.ts)", async () => {
  __resetFeedbackPacingForTests();
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  // A findBy can resolve on the commit, before its passive effects run.
  const effectsFlushed = () => act(async () => {});
  render(<RetentionCheck userId="u1" courses={courses} />);
  expect(feedbackHeld()).toBe(false); // the entry card alone is not an activity
  await open();
  await effectsFlushed();
  expect(feedbackHeld()).toBe(true);
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "My own remembered explanation" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  await screen.findByTestId("retention-result");
  await effectsFlushed();
  expect(feedbackHeld()).toBe(true);
  fireEvent.click(screen.getByTestId("retention-next"));
  expect(screen.getByTestId("retention-finished")).toBeTruthy();
  expect(feedbackHeld()).toBe(false);
});

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
  expect(api.answerRetentionCheck).toHaveBeenCalledWith({ user_id: "u1", node_id: "n1", question_hash: "qh", answer: "My own remembered explanation", idk: false, ...VISIBLE });
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
  expect(api.answerRetentionCheck).toHaveBeenLastCalledWith({ user_id: "u1", node_id: "n1", question_hash: "qh", selected_option: "B", reason: "My reasoning", idk: false, ...VISIBLE });
  fireEvent.click(screen.getByTestId("retention-next")); fireEvent.click(screen.getByTestId("retention-idk"));
  await waitFor(() => expect(api.answerRetentionCheck).toHaveBeenLastCalledWith({ user_id: "u1", node_id: "n1", question_hash: "next", idk: true, ...VISIBLE }));
});

// ── spec §13 A126: the display stamp and the page-hidden telemetry ───────────

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

it("stamps each item's first display, once, and never before an explicit open", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item, { ...item, question_hash: "next" }] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  api.markRetentionShown.mockResolvedValue({ served: true });
  render(<RetentionCheck userId="u1" courses={courses} />);
  expect(api.markRetentionShown).not.toHaveBeenCalled(); // the entry card is not a display
  await open();
  await waitFor(() => expect(api.markRetentionShown).toHaveBeenCalledWith({ user_id: "u1", node_id: "n1", question_hash: "qh" }));
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit")); await screen.findByTestId("retention-result");
  expect(api.markRetentionShown).toHaveBeenCalledTimes(1); // a re-render is not a new display
  fireEvent.click(screen.getByTestId("retention-next"));
  await waitFor(() => expect(api.markRetentionShown).toHaveBeenLastCalledWith({ user_id: "u1", node_id: "n1", question_hash: "next" }));
  expect(api.markRetentionShown).toHaveBeenCalledTimes(2);
});

it("stamps a display once even when React mounts the effect twice (StrictMode)", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.markRetentionShown.mockResolvedValue({ served: true });
  render(<React.StrictMode><RetentionCheck userId="u1" courses={courses} /></React.StrictMode>);
  await open();
  await act(async () => {});
  expect(api.markRetentionShown).toHaveBeenCalledTimes(1);
});

it("counts the page-hidden time of each item from its own display", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item, { ...item, question_hash: "next" }] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  await act(async () => {});
  setVisibility("hidden");
  setVisibility("visible");
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit")); await screen.findByTestId("retention-result");
  expect(api.answerRetentionCheck.mock.calls[0][0].hidden_count).toBe(1);
  fireEvent.click(screen.getByTestId("retention-next"));
  await act(async () => {});
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "y" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  await waitFor(() => expect(api.answerRetentionCheck).toHaveBeenCalledTimes(2));
  expect(api.answerRetentionCheck.mock.calls[1][0]).toMatchObject({ question_hash: "next", hidden_count: 0, hidden_s: 0 });
});

it("a failed display stamp never blocks the check", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  api.markRetentionShown.mockRejectedValue(new ApiError("unavailable", 503));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  expect(await screen.findByTestId("retention-result")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("reports how often and how long the page was hidden while the item was on screen", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["Date"] });
  try {
    api.startRetentionCheck.mockResolvedValue({ items: [item] });
    api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
    render(<RetentionCheck userId="u1" courses={courses} />); await open();
    await act(async () => {});
    setVisibility("hidden");
    vi.setSystemTime(Date.now() + 30_000);
    setVisibility("visible");
    setVisibility("hidden");
    vi.setSystemTime(Date.now() + 12_000);
    setVisibility("visible");
    fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("retention-submit")); await screen.findByTestId("retention-result");
    const sent = api.answerRetentionCheck.mock.calls[0][0];
    expect(sent.hidden_count).toBe(2);
    expect(sent.hidden_s).toBeGreaterThanOrEqual(42);
    expect(sent.hidden_s).toBeLessThan(43);
  } finally {
    setVisibility("visible");
    vi.useRealTimers();
  }
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

it("shows the crisis-support card instead of a result; the check stays open (docs/safety/crisis-support.md)", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck
    .mockResolvedValueOnce({ graded: false, reply: "…", crisis_support: crisisFixture })
    .mockResolvedValueOnce({ correct: true, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />);
  await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "i want to end my life" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.textContent).toContain(crisisFixture.title);
  expect(screen.queryByTestId("retention-result")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull(); // the card is not an error
  fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
  expect((screen.getByTestId("retention-answer") as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "My own remembered explanation" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  expect(await screen.findByTestId("retention-result")).toBeTruthy();
});

// ── F4: a deep link to a course that is not in the list says so ─────────────

it("a deep link to a course outside the list falls back to the first course and says so until one is picked", () => {
  render(<RetentionCheck userId="u1" courses={courses} initialCourseId="c9" />);
  const select = screen.getByTestId("retention-course") as HTMLSelectElement;
  expect(select.value).toBe("c1");
  const note = screen.getByTestId("retention-course-fallback");
  expect(note.textContent).toContain("isn't one of your courses");
  expect(note.textContent).toContain("Computer Science");
  expect(select).toHaveAccessibleDescription(note.textContent!);
  fireEvent.change(select, { target: { value: "c2" } });
  expect(screen.queryByTestId("retention-course-fallback")).toBeNull();
});

it("a deep link to a listed course, and no link at all, show no fallback note", () => {
  const { unmount } = render(<RetentionCheck userId="u1" courses={courses} initialCourseId="c2" />);
  expect((screen.getByTestId("retention-course") as HTMLSelectElement).value).toBe("c2");
  expect(screen.queryByTestId("retention-course-fallback")).toBeNull();
  unmount();
  render(<RetentionCheck userId="u1" courses={courses} />);
  expect(screen.queryByTestId("retention-course-fallback")).toBeNull();
});

it("says nothing while the course list is still empty (loading)", () => {
  const { rerender } = render(<RetentionCheck userId="u1" courses={[]} initialCourseId="c2" />);
  expect(screen.queryByTestId("retention-course-fallback")).toBeNull();
  rerender(<RetentionCheck userId="u1" courses={courses} initialCourseId="c2" />);
  expect((screen.getByTestId("retention-course") as HTMLSelectElement).value).toBe("c2");
  expect(screen.queryByTestId("retention-course-fallback")).toBeNull();
});

// ── F4: a withdrawn item (404) moves on instead of failing every resend ─────

it("a 404 on an answer skips to the next question with a note", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item, { ...item, question_hash: "next", prompt: "Second?" }] });
  api.answerRetentionCheck.mockRejectedValueOnce(new ApiError("check item not found", 404));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  expect(await screen.findByTestId("retention-skipped")).toBeTruthy();
  expect(screen.getByText("Second?")).toBeTruthy();
  expect(screen.getByText("Question 2 of 2")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect((screen.getByTestId("retention-answer") as HTMLTextAreaElement).value).toBe("");
  await waitFor(() => expect(screen.getByTestId("retention-answer")).toHaveFocus());
});

it("a 404 on the last question finishes the set, noting the skip", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockRejectedValueOnce(new ApiError("check item not found", 404));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.click(screen.getByTestId("retention-idk"));
  expect(await screen.findByTestId("retention-finished")).toBeTruthy();
  expect(screen.getByTestId("retention-skipped")).toBeTruthy();
  await waitFor(() => expect(screen.getByTestId("retention-finished")).toHaveFocus());
});

// ── F8: focus moves with the action; results land in a live region ─────────

it("Open moves focus to the first answer, Check answer to the result, Continue to the next answer", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item, { ...item, question_hash: "next" }] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />);
  screen.getByTestId("retention-open").focus();
  await open();
  await waitFor(() => expect(screen.getByTestId("retention-answer")).toHaveFocus());
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  await waitFor(() => expect(screen.getByTestId("retention-result")).toHaveFocus());
  fireEvent.click(screen.getByTestId("retention-next"));
  await waitFor(() => expect(screen.getByTestId("retention-answer")).toHaveFocus());
});

it("an mc_reason question takes focus on its first option; the last Continue focuses the finished line", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [{ ...item, format: "mc_reason", options: [{ letter: "A", text: "First" }, { letter: "B", text: "Second" }] }] });
  api.answerRetentionCheck.mockResolvedValue({ correct: false, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  await waitFor(() => expect(screen.getByRole("radio", { name: "A. First" })).toHaveFocus());
  fireEvent.click(screen.getByTestId("retention-idk"));
  await waitFor(() => expect(screen.getByTestId("retention-result")).toHaveFocus());
  fireEvent.click(screen.getByTestId("retention-next"));
  await waitFor(() => expect(screen.getByTestId("retention-finished")).toHaveFocus());
});

it("an empty set focuses the line that says so", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [] });
  render(<RetentionCheck userId="u1" courses={courses} />);
  fireEvent.click(screen.getByTestId("retention-open"));
  await waitFor(() => expect(screen.getByTestId("retention-empty")).toHaveFocus());
});

it("writes the result into a live region that was already on the page", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockResolvedValue({ correct: true, confidence: 0.9 });
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  const region = screen.getByTestId("retention-item").querySelector('[aria-live="polite"]');
  expect(region).toBeEmptyDOMElement();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "x" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  expect(region).toContainElement(await screen.findByTestId("retention-result"));
});

it("a status line (empty set) is written into a live region that was already on the page", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [] });
  render(<RetentionCheck userId="u1" courses={courses} />);
  const region = screen.getByTestId("retention-open").parentElement!.querySelector('[aria-live="polite"]');
  expect(region).toBeEmptyDOMElement();
  fireEvent.click(screen.getByTestId("retention-open"));
  expect(region).toContainElement(await screen.findByTestId("retention-empty"));
});

it("a failed answer focuses its error and keeps the typed answer", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  api.answerRetentionCheck.mockRejectedValueOnce(new ApiError("unavailable", 503));
  render(<RetentionCheck userId="u1" courses={courses} />); await open();
  fireEvent.change(screen.getByTestId("retention-answer"), { target: { value: "kept" } });
  fireEvent.click(screen.getByTestId("retention-submit"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
  expect((screen.getByTestId("retention-answer") as HTMLTextAreaElement).value).toBe("kept");
});

it("the open control is a compact primary button until a set is open", async () => {
  api.startRetentionCheck.mockResolvedValue({ items: [item] });
  render(<RetentionCheck userId="u1" courses={courses} />);
  const button = screen.getByTestId("retention-open");
  expect(button.className).toContain("btn--primary");
  // a block parent, so the card's flex column never stretches it across the card
  expect(button.parentElement?.tagName).toBe("DIV");
  expect(button.parentElement?.style.display).toBe("");
  await open();
  expect(screen.getByTestId("retention-open").className).not.toContain("btn--primary");
});
