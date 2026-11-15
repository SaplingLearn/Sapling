// @vitest-environment jsdom
/**
 * Notetaker AI actions and the crisis screen (docs/safety/crisis-support.md).
 * A crisis line the student TYPES into the notes chat is answered with the
 * card in its thread instead of a reply. A crisis line in the NOTE itself
 * never blocks: Summarize, Extract concepts, Send to tutor and the chat get
 * their normal result with the card alongside it (`crisis_support_alongside`),
 * and an error answer (a 429) that carries the card shows it too.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { ApiError, type EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote } from "@/lib/types";
import crisisFixture from "@/test-utils/crisisSupport.json";
import type { CrisisSupport } from "@/lib/crisisSupport";

const { push, toastError } = vi.hoisted(() => ({ push: vi.fn(), toastError: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/notetaker",
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: toastError, warn: vi.fn() }),
}));
vi.mock("@/components/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ApiError: (await importOriginal<typeof import("@/lib/api")>()).ApiError,
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
  extractNoteConcepts,
  getCourses,
  listNoteConcepts,
  listNotes,
  noteChat,
  patchNote,
  sendNoteToTutor,
  summarizeNote,
} from "@/lib/api";

const COURSE: EnrolledCourse = {
  enrollment_id: "e-cs", course_id: "c1", course_code: "CS-201", course_name: "Data Structures",
  school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
  enrolled_at: "2026-01-01", term: "Spring 2026",
};
const NOTE: ApiNote = {
  id: "n1", user_id: "u1", course_id: "c1", title: "Week 3", body: "Base case.", tags: [],
  last_summary: "An earlier summary.", last_summary_at: null,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
};
// The JSON import widens the action kinds to string; the payload is the backend's.
const CRISIS = { reply: "the card as text", crisis_support: crisisFixture as CrisisSupport };
// The card beside a normal result: the note's own content matched.
const ALONGSIDE = { crisis_support: crisisFixture as CrisisSupport, crisis_support_alongside: true };

beforeEach(() => {
  Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
  vi.mocked(listNotes).mockResolvedValue({ notes: [NOTE] });
  vi.mocked(listNoteConcepts).mockResolvedValue({ concepts: [] });
  vi.mocked(patchNote).mockResolvedValue({} as ApiNote);
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

describe("notetaker — crisis support", () => {
  it("the notes chat shows the card in its thread, not as an AI message", async () => {
    vi.mocked(noteChat).mockResolvedValueOnce(CRISIS);
    await renderPage();
    const input = screen.getByPlaceholderText("Ask a quick question…");
    fireEvent.change(input, { target: { value: "i want to kill myself" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const card = await screen.findByTestId("crisis-support-card");
    expect(card).toHaveTextContent(crisisFixture.title);
    expect(screen.queryByText("the card as text")).toBeNull();
    expect(screen.queryByRole("alert", { hidden: true })).toBeNull();
    expect(input).not.toBeDisabled();
  });

  it("Summarize of a note that matched shows the new summary AND the card", async () => {
    vi.mocked(summarizeNote).mockResolvedValueOnce({ summary: "A fresh summary.", ...ALONGSIDE });
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Summarize note" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(crisisFixture.title);
    expect(await screen.findByText("A fresh summary.")).toBeTruthy();
    expect(screen.queryByText("An earlier summary.")).toBeNull();
    expect(toastError).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("A fresh summary.")).toBeTruthy();
  });

  it("a refused Summarize whose answer carries the card shows it beside the error", async () => {
    vi.mocked(summarizeNote).mockRejectedValueOnce(new ApiError("Too many requests.", 429, {
      body: { detail: "Too many requests.", crisis_support: crisisFixture },
    }));
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Summarize note" }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    expect(toastError).toHaveBeenCalled();
    expect(screen.getByText("An earlier summary.")).toBeTruthy();
  });

  it("Extract concepts of a note that matched links the concepts AND shows the card", async () => {
    vi.mocked(extractNoteConcepts).mockResolvedValueOnce({ concepts: ["Recursion"], linked: 1, ...ALONGSIDE });
    await renderPage();
    await waitFor(() => expect(listNoteConcepts).toHaveBeenCalled());
    const reads = vi.mocked(listNoteConcepts).mock.calls.length;
    fireEvent.click(await screen.findByRole("button", { name: /extract concepts/i }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    await waitFor(() => expect(vi.mocked(listNoteConcepts).mock.calls.length).toBeGreaterThan(reads));
  });

  it("Send to tutor of a note that matched shows the card, then opens the tutor once it is closed", async () => {
    vi.mocked(sendNoteToTutor).mockResolvedValueOnce({ topic: "Week 3", course_id: "c1", preface: "", ...ALONGSIDE });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
    // The note rides along, so starting on its title is not screened as typed.
    await waitFor(() => expect(push).toHaveBeenCalledWith("/learn?topic=Week%203&course=c1&note=n1"));
  });

  it("Send to tutor of an ordinary note opens the tutor on its title, naming the note", async () => {
    vi.mocked(sendNoteToTutor).mockResolvedValueOnce({ topic: "Week 3", course_id: "c1", preface: "" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/learn?topic=Week%203&course=c1&note=n1"));
  });

  it("the notes chat on a note that matched shows the card AND the reply", async () => {
    vi.mocked(noteChat).mockResolvedValueOnce({ reply: "A base case stops the recursion.", ...ALONGSIDE });
    await renderPage();
    const input = screen.getByPlaceholderText("Ask a quick question…");
    fireEvent.change(input, { target: { value: "what is a base case?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByTestId("crisis-support-card")).toHaveTextContent(crisisFixture.title);
    expect(screen.getByText("A base case stops the recursion.")).toBeTruthy();
  });

  it("a blocked action (no result, the card only) still does none of its own work", async () => {
    vi.mocked(sendNoteToTutor).mockResolvedValueOnce(CRISIS);
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(push).not.toHaveBeenCalled();
  });
});
