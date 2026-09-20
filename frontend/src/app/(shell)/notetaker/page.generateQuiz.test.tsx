// @vitest-environment jsdom
/**
 * "Generate quiz" deep link + `?note=` reopen (#537 §6, C3).
 *
 * Before this change the button pushed a bare `/quiz?concept=<id>` — the quiz
 * screen's Done/Cancel/Leave always landed on the hardcoded `/learn` (R5 §C),
 * because nothing on the notetaker side carried a source or a way back to a
 * specific note. Now the button builds its href through
 * `lib/quiz/source.ts::buildQuizHref` (`quizHrefForNote`, exported at the
 * bottom of `page.tsx`), and the page itself understands `?note=<id>` as the
 * arrival half of that round trip.
 *
 * Renders the real page (mirrors `page.testmode.test.tsx`'s mocking strategy)
 * rather than only unit-testing `quizHrefForNote` in isolation, since the
 * disabled-until-linked gating and the `?note=` mount behaviour both live in
 * the component itself.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote, LinkedConcept as ApiLinkedConcept } from "@/lib/types";

const push = vi.fn();
let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => searchParamsValue,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/components/ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warn: vi.fn() }),
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

import NotetakerPage, { quizHrefForNote } from "./page";
import {
  listNotes,
  listNoteConcepts,
  getCourses,
  generateQuizFromNote,
} from "@/lib/api";

const mockedListNotes = vi.mocked(listNotes);
const mockedListConcepts = vi.mocked(listNoteConcepts);
const mockedGetCourses = vi.mocked(getCourses);
const mockedGenerateQuiz = vi.mocked(generateQuizFromNote);

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

// Active by default: `notes[0]` (per apiNoteToNote + the initial-load effect).
const NOTE_LINKED: ApiNote = {
  id: "n1",
  user_id: "u1",
  course_id: "c1",
  title: "Recursion",
  body: "Base case + recursive case.",
  tags: [],
  last_summary: null,
  last_summary_at: null,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const NOTE_UNLINKED: ApiNote = {
  ...NOTE_LINKED,
  id: "n2",
  title: "Loops",
};

const LINKED_CONCEPT: ApiLinkedConcept = {
  id: "concept-1",
  concept_name: "Recursion",
  mastery_tier: "learning",
  mastery_score: 0.4,
  course_id: "c1",
};

beforeEach(() => {
  Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  searchParamsValue = new URLSearchParams();
  mockedGetCourses.mockResolvedValue({ courses: [COURSE] });
  mockedListNotes.mockResolvedValue({ notes: [NOTE_LINKED, NOTE_UNLINKED] });
  mockedListConcepts.mockImplementation(async (noteId: string) => ({
    concepts: noteId === "n1" ? [LINKED_CONCEPT] : [],
  }));
  mockedGenerateQuiz.mockResolvedValue({ concept_node_id: "concept-1", concept_name: "Recursion" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("quizHrefForNote (pure)", () => {
  it("carries the concept, the notes source and a return path that reopens the note", () => {
    const href = quizHrefForNote("n1", "concept-1");
    expect(href).toBe("/quiz?concept=concept-1&from=notes&return=%2Fnotetaker%3Fnote%3Dn1&note=n1");
  });
});

describe("Generate quiz button", () => {
  it("stays disabled until the active note has a linked concept", async () => {
    render(<NotetakerPage />);
    await screen.findByPlaceholderText("Untitled note");

    // n1 ("Recursion") is active by default and has LINKED_CONCEPT.
    const button = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(button).not.toBeDisabled());

    // Switch to n2 ("Loops"), which has no linked concepts.
    fireEvent.click(screen.getByText("Loops"));
    await waitFor(() => expect(button).toBeDisabled());
  });

  it("pushes a deep link with concept=, from=notes, note=<id> and an encoded return= reopening the note", async () => {
    render(<NotetakerPage />);
    await screen.findByPlaceholderText("Untitled note");
    const button = await screen.findByRole("button", { name: /generate quiz/i });
    await waitFor(() => expect(button).not.toBeDisabled());

    fireEvent.click(button);

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    const href = push.mock.calls[0][0] as string;
    expect(href.startsWith("/quiz?")).toBe(true);

    const params = new URLSearchParams(href.slice(href.indexOf("?") + 1));
    expect(params.get("concept")).toBe("concept-1");
    expect(params.get("from")).toBe("notes");
    expect(params.get("note")).toBe("n1");
    expect(params.get("return")).toBe("/notetaker?note=n1");
  });
});

describe("?note=<id> reopens a specific note on mount", () => {
  it("makes the named note active when it exists in the loaded list", async () => {
    searchParamsValue = new URLSearchParams("note=n2");
    render(<NotetakerPage />);

    await waitFor(async () => {
      const title = await screen.findByPlaceholderText("Untitled note");
      expect((title as HTMLInputElement).value).toBe("Loops");
    });
  });

  it("ignores an unknown note id and keeps the default active note", async () => {
    searchParamsValue = new URLSearchParams("note=does-not-exist");
    render(<NotetakerPage />);

    await waitFor(async () => {
      const title = await screen.findByPlaceholderText("Untitled note");
      expect((title as HTMLInputElement).value).toBe("Recursion");
    });
  });
});
