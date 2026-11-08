// @vitest-environment jsdom
/**
 * Notetaker AI actions answered by the crisis screen
 * (docs/safety/crisis-support.md): the notes chat shows the card in its
 * thread; Summarize, Extract concepts and Send to tutor show it over the page
 * and do none of their own work (no summary, no concepts, no tutor session).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote } from "@/lib/types";
import crisisFixture from "@/test-utils/crisisSupport.json";
import type { CrisisSupport } from "@/lib/crisisSupport";

const { push, toastError } = vi.hoisted(() => ({ push: vi.fn(), toastError: vi.fn() }));

vi.mock("next/navigation", () => ({
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

  it("Summarize shows the card and keeps the note's summary as it was", async () => {
    vi.mocked(summarizeNote).mockResolvedValueOnce(CRISIS);
    await renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Summarize note" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(crisisFixture.title);
    expect(screen.getByText("An earlier summary.")).toBeTruthy();
    expect(toastError).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("crisis-support-dismiss"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Extract concepts shows the card and links nothing", async () => {
    vi.mocked(extractNoteConcepts).mockResolvedValueOnce(CRISIS);
    await renderPage();
    await waitFor(() => expect(listNoteConcepts).toHaveBeenCalled());
    const reads = vi.mocked(listNoteConcepts).mock.calls.length;
    fireEvent.click(await screen.findByRole("button", { name: /extract concepts/i }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    expect(vi.mocked(listNoteConcepts).mock.calls.length).toBe(reads); // no refresh: nothing changed
  });

  it("Send to tutor shows the card and opens no tutor session", async () => {
    vi.mocked(sendNoteToTutor).mockResolvedValueOnce(CRISIS);
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Send to tutor" }));
    expect((await screen.findByRole("dialog")).textContent).toContain(crisisFixture.title);
    expect(push).not.toHaveBeenCalled();
  });
});
