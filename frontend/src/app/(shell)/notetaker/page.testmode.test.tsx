// @vitest-environment jsdom
/**
 * NEXT_PUBLIC_TEST_MODE determinism for the notetaker's edit stamp (#426).
 *
 * `updateActive` stamps `updatedAt` on every keystroke, and `relTime` (the
 * "Xm ago" labels in the notes list + detail rail) measures against the
 * frozen `now()`. The stamp must come from the same frozen clock — before
 * the fix it was `new Date()` (real wall clock), so a freshly edited note's
 * age was measured real-clock-to-frozen-clock and rendered a wall-clock-
 * dependent label.
 *
 * The test pins the REAL clock 2 hours before the frozen instant: a buggy
 * stamp makes the just-edited note render "2h ago"; the frozen stamp renders
 * "just now".
 *
 * Module-loading strategy mirrors KnowledgeGraph2D.testmode.test.tsx: the
 * flag is captured when `@/lib/testMode` first evaluates, so stub the env
 * at file scope and import the page lazily in beforeAll.
 */

import React from "react";
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote } from "@/lib/types";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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

let NotetakerPage: (typeof import("./page"))["default"];

beforeAll(async () => {
  // jsdom implements no Element.scrollTo; the AI chat panel calls it on mount.
  Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  ({ default: NotetakerPage } = await import("./page"));
});

import { listNotes, listNoteConcepts, getCourses, patchNote } from "@/lib/api";

const mockedListNotes = vi.mocked(listNotes);
const mockedListConcepts = vi.mocked(listNoteConcepts);
const mockedGetCourses = vi.mocked(getCourses);
const mockedPatchNote = vi.mocked(patchNote);

// The frozen test-mode instant this file injects, and a real wall clock
// pinned 2 hours earlier — far enough that a real-clock stamp is visible
// ("2h ago") but the seeded note itself still reads "just now".
const FROZEN_MS = Date.UTC(2026, 2, 11, 12, 0, 0);
const REAL_MS = FROZEN_MS - 2 * 60 * 60 * 1000;

const COURSE: EnrolledCourse = {
  enrollment_id: "e-bio",
  course_id: "c1",
  course_code: "BIO-101",
  course_name: "Biology",
  school: "BU",
  department: "BIO",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term: "Spring 2026",
};

const NOTE: ApiNote = {
  id: "n1",
  user_id: "u1",
  course_id: "c1",
  title: "Osmosis",
  body: "Water moves across membranes.",
  tags: [],
  last_summary: null,
  last_summary_at: null,
  created_at: new Date(FROZEN_MS).toISOString(),
  updated_at: new Date(FROZEN_MS).toISOString(),
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(REAL_MS));
  globalThis.__SAPLING_TEST_NOW__ = FROZEN_MS;
  mockedGetCourses.mockResolvedValue({ courses: [COURSE] });
  mockedListNotes.mockResolvedValue({ notes: [NOTE] });
  mockedListConcepts.mockResolvedValue({ concepts: [] });
  mockedPatchNote.mockResolvedValue(NOTE);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
  globalThis.__SAPLING_TEST_NOW__ = undefined;
});

describe("NotetakerPage updateActive under NEXT_PUBLIC_TEST_MODE (#426)", () => {
  it("stamps edits with the frozen clock, so a fresh edit reads 'just now', never a wall-clock age", async () => {
    render(<NotetakerPage />);

    const title = await screen.findByPlaceholderText("Untitled note");
    // Sanity: the untouched seeded note measures frozen-to-frozen.
    expect(screen.getAllByText("just now").length).toBeGreaterThan(0);

    fireEvent.change(title, { target: { value: "Osmosis II" } });

    // A real-clock stamp (REAL_MS, 2h before the frozen instant) would
    // render "2h ago" in the notes list / detail rail.
    expect(screen.queryAllByText("2h ago")).toHaveLength(0);
    expect(screen.getAllByText("just now").length).toBeGreaterThan(0);
  });
});
