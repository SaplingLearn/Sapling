// @vitest-environment jsdom
/**
 * Study — opening a guide from the "Recent guides" rail (#476).
 *
 * The defect is NOT that the open path forgets to select the exam: openRecent
 * sets courseId AND examId together. It's that the courseId-keyed exams effect
 * opens with an unconditional `setExamId("")` — a scope reset that can't tell
 * "the user switched course" (selection now invalid) from "we just opened a
 * specific guide" (selection deliberate and valid). Both effects run in the
 * same commit, so the guide still loads, and the NEXT render has examId "" —
 * which is why the symptom is "guide on screen, Regenerate permanently
 * disabled" rather than "nothing opens".
 *
 * The discriminator that proves the mechanism is the same-course case: a rail
 * entry for the ALREADY-selected course never trips the effect, so it works
 * today. It's pinned below as a control.
 *
 * Regenerate's term is part of this fix, not a separate concern: the button is
 * unreachable on the rail path today, so nothing could regenerate a rail-opened
 * guide under the wrong term. Making it reachable exposes that hazard — the
 * #475 F1 mismatch (a Spring guide regenerated as Fall silently persists a row
 * against the wrong offering) — so regenerate has to replay the term the
 * displayed guide was actually loaded with.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

// Pulls in the whole import-tab tree (and more @/lib/api names) — out of scope.
vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: () => null,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getStudyGuideExams: vi.fn(async () => ({ exams: [] })),
  getStudyGuide: vi.fn(async () => ({
    guide: { exam: "Midterm 1", topics: [] },
    generated_at: "2026-04-01T00:00:00Z",
    cached: true,
  })),
  regenerateStudyGuide: vi.fn(async () => ({
    success: true,
    guide: { exam: "Midterm 1", topics: [] },
    generated_at: "2026-04-02T00:00:00Z",
  })),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
import {
  getCachedStudyGuides,
  getCourses,
  getStudyGuide,
  getStudyGuideExams,
  regenerateStudyGuide,
  type EnrolledCourse,
} from "@/lib/api";

const mockedCached = vi.mocked(getCachedStudyGuides);
const mockedCourses = vi.mocked(getCourses);
const mockedExams = vi.mocked(getStudyGuideExams);
const mockedGuide = vi.mocked(getStudyGuide);
const mockedRegenerate = vi.mocked(regenerateStudyGuide);

/** The rail entry under test: course c1 / exam e1, generated under Fall 2025. */
const RECENT = {
  id: "g1",
  course_id: "c1",
  exam_id: "e1",
  course_name: "Intro to CS",
  exam_title: "Midterm 1",
  overview: "",
  generated_at: "2026-04-01T00:00:00Z",
  semester: "Fall 2025",
};

function course(id: string, code: string, name: string, term: string): EnrolledCourse {
  return {
    enrollment_id: `enr-${id}`,
    course_id: id,
    course_code: code,
    course_name: name,
    school: "BU",
    department: "CS",
    color: null,
    nickname: null,
    node_count: 0,
    enrolled_at: "2025-09-01",
    term,
  };
}

const COURSE_C1 = course("c1", "CS101", "Intro to CS", "Fall 2025");
const COURSE_C2 = course("c2", "CS201", "Data Structures", "Fall 2025");

/** The two CustomSelect triggers in DOM order: [course, exam]. They're the only
 *  listbox triggers on the guide pane, and querying by accessible name can't
 *  distinguish them once both hold a value. */
function selectTriggers() {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="listbox"]'),
  );
}

const examTrigger = () => selectTriggers()[1];

function renderStudy() {
  return render(
    <ToastProvider>
      <Study />
    </ToastProvider>,
  );
}

/** Opens the rail entry titled "Midterm 1" (the aside is the only place that
 *  title renders as a clickable button before an exam is selected). */
async function openRecentGuide() {
  await userEvent.click(await screen.findByText("Midterm 1"));
}

beforeEach(() => {
  mockedCached.mockResolvedValue({ guides: [RECENT] });
  mockedCourses.mockResolvedValue({ courses: [COURSE_C1, COURSE_C2] });
  mockedExams.mockResolvedValue({
    exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-04-01" }],
  });
});

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(ACTIVE_SEMESTER_STORAGE_KEY);
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Study — opening a guide from the Recent guides rail (#476)", () => {
  it("keeps the exam selected, so Regenerate is usable", async () => {
    renderStudy();
    await openRecentGuide();

    // The guide is on screen — the load was never the broken part.
    await screen.findByRole("button", { name: /regenerate/i });
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeEnabled();
  });

  it("regenerates the exam that was opened", async () => {
    renderStudy();
    await openRecentGuide();

    await userEvent.click(await screen.findByRole("button", { name: /regenerate/i }));

    await waitFor(() => expect(mockedRegenerate).toHaveBeenCalledTimes(1));
    expect(mockedRegenerate).toHaveBeenCalledWith("u1", "c1", "e1", expect.anything());
  });

  it("regenerates under the entry's OWN term, not the active selector's (#475 F1)", async () => {
    // The rail entry is a Fall 2025 guide; the active selector says Spring 2026.
    // Regenerating under Spring would build and persist a row against an
    // offering the displayed guide never came from.
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Spring 2026");
    mockedCourses.mockResolvedValue({
      courses: [course("c1", "CS101", "Intro to CS", "Spring 2026")],
    });

    renderStudy();
    await openRecentGuide();
    await userEvent.click(await screen.findByRole("button", { name: /regenerate/i }));

    await waitFor(() => expect(mockedRegenerate).toHaveBeenCalledTimes(1));
    expect(mockedRegenerate).toHaveBeenCalledWith("u1", "c1", "e1", "Fall 2025");
    expect(mockedRegenerate).not.toHaveBeenCalledWith("u1", "c1", "e1", "Spring 2026");
  });

  it("shows the opened exam in the exam picker", async () => {
    renderStudy();
    await openRecentGuide();

    await waitFor(() => expect(examTrigger()).toHaveTextContent("Midterm 1"));
  });

  // Control, not a new behavior: this path never changes courseId, so the
  // course-keyed reset never fires and it works today. It's what proves the
  // defect is the reset — and it must keep working after the fix.
  it("already worked when the entry's course was the selected one", async () => {
    renderStudy();
    await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));
    await userEvent.click(await screen.findByRole("option", { name: /CS101/ }));
    await openRecentGuide();

    expect(await screen.findByRole("button", { name: /regenerate/i })).toBeEnabled();
  });
});

describe("Study — selections that genuinely go stale still reset", () => {
  it("switching course clears the exam selected under the old one", async () => {
    renderStudy();
    await openRecentGuide();
    await screen.findByRole("button", { name: /regenerate/i });

    await userEvent.click(selectTriggers()[0]);
    await userEvent.click(await screen.findByRole("option", { name: /CS201/ }));

    await waitFor(() => expect(examTrigger()).toHaveTextContent(/pick an exam/i));
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
  });

  // CustomSelect.commit() fires onChange for the already-selected option too,
  // so "switching course" has to mean the value actually CHANGED. The old
  // effect-based reset got this for free (setCourseId(same) → React bails out,
  // the effect never re-runs); moving the reset onto the event dropped that
  // guard, and re-confirming your own course wiped the guide you were reading.
  it("re-picking the course already selected leaves the loaded guide alone", async () => {
    renderStudy();
    await openRecentGuide();
    await screen.findByRole("button", { name: /regenerate/i });

    await userEvent.click(selectTriggers()[0]);
    await userEvent.click(await screen.findByRole("option", { name: /CS101/ }));

    expect(screen.getByRole("button", { name: /regenerate/i })).toBeEnabled();
    expect(examTrigger()).toHaveTextContent("Midterm 1");
  });

  it("switching term drops the selection instead of reloading it under the new term", async () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    renderStudy();
    // Selected through the pickers, NOT the rail: the rail path is the one
    // #476 breaks, and setting up through it would leave examId already ""
    // here — the assertion below would pass without testing anything.
    await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));
    await userEvent.click(await screen.findByRole("option", { name: /CS101/ }));
    await userEvent.click(examTrigger());
    await userEvent.click(await screen.findByRole("option", { name: /Midterm 1/ }));
    await screen.findByRole("button", { name: /regenerate/i });
    mockedGuide.mockClear();

    // The Courses & Semesters hub switches the term via localStorage + this
    // same-tab event (lib/useActiveSemester).
    await act(async () => {
      window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Spring 2026");
      window.dispatchEvent(new Event("sapling-active-semester-change"));
    });

    // An exam picked under Fall need not exist in Spring — re-reading it under
    // the new term is a guess, and it lands on the strict resolver.
    await waitFor(() => expect(examTrigger()).toHaveTextContent(/pick an exam/i));
    expect(mockedGuide).not.toHaveBeenCalled();
  });
});
