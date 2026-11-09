// @vitest-environment jsdom
/**
 * Notetaker autosave + action + notes-chat state machines (#768).
 *
 * Page-level regressions for the wiring around `lib/notes/useNoteAutosave`
 * (whose own machine is unit-tested next to it):
 *   - a failed autosave surfaces "Couldn't save" + Retry, never a stuck
 *     "Saving…", and Retry re-sends the kept edit;
 *   - deleting a note with a queued edit never PATCHes the deleted note;
 *   - generate-quiz / send-to-tutor await the flushed save (and abort when it
 *     fails) instead of running against a stale body;
 *   - per-action busy state is cleared on success, not only on failure;
 *   - the notes chat drops a reply for a note that is no longer active, and
 *     renders a failure as an error state rather than a fake AI message.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote, LinkedConcept as ApiLinkedConcept } from "@/lib/types";

const { push, toastError } = vi.hoisted(() => ({ push: vi.fn(), toastError: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/components/ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: toastError, warn: vi.fn() }),
}));

vi.mock("@/components/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/lib/api", () => ({
  listNotes: vi.fn(),
  createNote: vi.fn(),
  patchNote: vi.fn(),
  deleteNote: vi.fn(),
  listNoteConcepts: vi.fn(),
  linkNoteConcept: vi.fn(),
  unlinkNoteConcept: vi.fn(),
  summarizeNote: vi.fn(),
  extractNoteConcepts: vi.fn(),
  generateQuizFromNote: vi.fn(),
  sendNoteToTutor: vi.fn(),
  noteChat: vi.fn(),
  getCourses: vi.fn(),
  getGraph: vi.fn(),
}));

import NotetakerPage from "./page";
import {
  listNotes,
  listNoteConcepts,
  getCourses,
  patchNote,
  deleteNote,
  generateQuizFromNote,
  sendNoteToTutor,
  noteChat,
} from "@/lib/api";

const mockedPatch = vi.mocked(patchNote);
const mockedDelete = vi.mocked(deleteNote);
const mockedQuiz = vi.mocked(generateQuizFromNote);
const mockedTutor = vi.mocked(sendNoteToTutor);
const mockedChat = vi.mocked(noteChat);

const COURSE: EnrolledCourse = {
  enrollment_id: "e-cs",
  course_id: "c1",
  course_code: "CS-201",
  course_name: "Data Structures",
  school: "BU",
  department: "CS",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term: "Spring 2026",
};

const NOTE_A: ApiNote = {
  id: "n1",
  user_id: "u1",
  course_id: "c1",
  title: "Recursion",
  body: "Base case.",
  tags: [],
  last_summary: null,
  last_summary_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};
const NOTE_B: ApiNote = { ...NOTE_A, id: "n2", title: "Loops", body: "for / while." };

const LINKED: ApiLinkedConcept = {
  id: "concept-1",
  concept_name: "Recursion",
  mastery_tier: "learning",
  mastery_score: 0.4,
  course_id: "c1",
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
  vi.mocked(listNotes).mockResolvedValue({ notes: [NOTE_A, NOTE_B] });
  vi.mocked(listNoteConcepts).mockImplementation(async (noteId: string) => ({
    concepts: noteId === "n1" ? [LINKED] : [],
  }));
  mockedPatch.mockResolvedValue({} as ApiNote);
  mockedQuiz.mockResolvedValue({ concept_node_id: "concept-1", concept_name: "Recursion" });
  mockedTutor.mockResolvedValue({ topic: "Recursion", course_id: "c1", preface: "" });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderPage() {
  render(<NotetakerPage />);
  await screen.findByPlaceholderText("Untitled note");
}

const body = () =>
  screen.getByPlaceholderText(
    "Start writing — Sapling will pick up concepts as you go.",
  ) as HTMLTextAreaElement;

describe("autosave footer", () => {
  it("a failed save shows Couldn't save + Retry (not a stuck Saving…) and Retry re-sends the edit", async () => {
    mockedPatch.mockRejectedValueOnce(new Error("500"));
    await renderPage();
    fireEvent.change(body(), { target: { value: "Base case. Plus recursion." } });

    await screen.findByText(/Couldn.t save/, {}, { timeout: 3000 });
    expect(screen.queryByText("Saving…")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(2));
    expect(mockedPatch.mock.calls[1][2]).toEqual({ body: "Base case. Plus recursion." });
    await screen.findByText(/^Saved ·/);
  });
});

describe("deleting a note with a queued edit", () => {
  it("never PATCHes the deleted note", async () => {
    mockedDelete.mockResolvedValue({ deleted: true } as never);
    await renderPage();
    fireEvent.change(body(), { target: { value: "edit right before delete" } });
    fireEvent.click(screen.getByRole("button", { name: /Delete note/ }));

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("n1", "u1"));
    // The editor moves to the remaining note.
    await waitFor(() =>
      expect((screen.getByPlaceholderText("Untitled note") as HTMLInputElement).value).toBe(
        "Loops",
      ),
    );
    // Well past the debounce: still no PATCH, and the footer is not stuck.
    await new Promise((r) => setTimeout(r, 1000));
    expect(mockedPatch).not.toHaveBeenCalled();
    expect(screen.queryByText("Saving…")).toBeNull();
  });

  it("re-queues the edit when the delete fails", async () => {
    mockedDelete.mockRejectedValue(new Error("500"));
    await renderPage();
    fireEvent.change(body(), { target: { value: "keep this" } });
    fireEvent.click(screen.getByRole("button", { name: /Delete note/ }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(mockedPatch.mock.calls[0][0]).toBe("n1");
    expect(mockedPatch.mock.calls[0][2]).toEqual({ body: "keep this" });
  });
});

describe("generate quiz / send to tutor wait for the save", () => {
  it("generate quiz runs only after the latest body has landed", async () => {
    const save = deferred<ApiNote>();
    mockedPatch.mockReturnValueOnce(save.promise);
    await renderPage();
    const quiz = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(quiz).not.toBeDisabled());

    fireEvent.change(body(), { target: { value: "fresh body" } });
    fireEvent.click(quiz);

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedPatch.mock.calls[0][2]).toEqual({ body: "fresh body" });
    expect(mockedQuiz).not.toHaveBeenCalled();

    await act(async () => save.resolve({} as ApiNote));
    await waitFor(() => expect(mockedQuiz).toHaveBeenCalledWith("n1", "u1"));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
  });

  it("generate quiz aborts with a message when the save fails", async () => {
    mockedPatch.mockRejectedValueOnce(new Error("500"));
    await renderPage();
    const quiz = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(quiz).not.toBeDisabled());

    fireEvent.change(body(), { target: { value: "fresh body" } });
    fireEvent.click(quiz);

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(mockedQuiz).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate quiz/i })).not.toBeDisabled(),
    );
  });

  it("send to tutor runs only after the latest body has landed", async () => {
    const save = deferred<ApiNote>();
    mockedPatch.mockReturnValueOnce(save.promise);
    await renderPage();

    fireEvent.change(body(), { target: { value: "fresh body" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));

    await waitFor(() => expect(mockedPatch).toHaveBeenCalledTimes(1));
    expect(mockedTutor).not.toHaveBeenCalled();
    await act(async () => save.resolve({} as ApiNote));
    await waitFor(() => expect(mockedTutor).toHaveBeenCalledWith("n1", "u1"));
  });
});

describe("per-action busy state", () => {
  it("is cleared after a successful generate quiz (not left set until unmount)", async () => {
    await renderPage();
    const quiz = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(quiz).not.toBeDisabled());
    fireEvent.click(quiz);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send to tutor" })).not.toBeDisabled(),
    );
    expect(screen.queryByText("Building quiz…")).toBeNull();
  });

  it("is cleared after a successful send to tutor", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Summarize note" })).not.toBeDisabled(),
    );
    expect(screen.queryByText("Opening tutor…")).toBeNull();
  });

  it("an action running on one note does not lock or relabel another note's actions", async () => {
    const quiz = deferred<{ concept_node_id: string; concept_name: string }>();
    mockedQuiz.mockReturnValueOnce(quiz.promise);
    await renderPage();
    const btn = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(btn).not.toBeDisabled());
    fireEvent.click(btn);
    await screen.findByText("Building quiz…");

    fireEvent.click(screen.getByText("Loops"));
    await waitFor(() =>
      expect((screen.getByPlaceholderText("Untitled note") as HTMLInputElement).value).toBe(
        "Loops",
      ),
    );
    expect(screen.queryByText("Building quiz…")).toBeNull();
    expect(screen.getByRole("button", { name: "Summarize note" })).not.toBeDisabled();
    await act(async () => quiz.resolve({ concept_node_id: "concept-1", concept_name: "R" }));
  });
});

describe("notes chat", () => {
  const chatInput = () => screen.getByPlaceholderText("Ask a quick question…");

  it("drops a reply that arrives after switching to another note", async () => {
    const reply = deferred<{ reply: string }>();
    mockedChat.mockReturnValueOnce(reply.promise);
    await renderPage();

    fireEvent.change(chatInput(), { target: { value: "what is a base case?" } });
    fireEvent.keyDown(chatInput(), { key: "Enter" });
    await waitFor(() => expect(mockedChat).toHaveBeenCalledWith("n1", "u1", "what is a base case?"));

    fireEvent.click(screen.getByText("Loops"));
    await waitFor(() =>
      expect((screen.getByPlaceholderText("Untitled note") as HTMLInputElement).value).toBe(
        "Loops",
      ),
    );
    // The new note's composer is usable right away, not stuck on the old send.
    expect(chatInput()).not.toBeDisabled();

    await act(async () => reply.resolve({ reply: "REPLY FOR NOTE A" }));
    expect(screen.queryByText("REPLY FOR NOTE A")).toBeNull();
    expect(screen.queryByText("Sapling is thinking…")).toBeNull();
  });

  it("renders a failure as an error state, not as an AI message, and restores the question", async () => {
    mockedChat.mockRejectedValueOnce(new Error("500"));
    await renderPage();

    fireEvent.change(chatInput(), { target: { value: "explain recursion" } });
    fireEvent.keyDown(chatInput(), { key: "Enter" });

    // The chat rail is aria-hidden until fullscreen, hence `hidden: true`.
    const alert = await screen.findByRole("alert", { hidden: true });
    expect(alert).toHaveTextContent("Sorry — something went wrong. Try again?");
    expect((chatInput() as HTMLInputElement).value).toBe("explain recursion");

    // A successful resend clears the error.
    mockedChat.mockResolvedValueOnce({ reply: "Recursion is…" });
    fireEvent.keyDown(chatInput(), { key: "Enter" });
    await screen.findByText("Recursion is…");
    expect(screen.queryByRole("alert", { hidden: true })).toBeNull();
  });
});
