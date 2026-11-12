// @vitest-environment jsdom
/**
 * Study — guide pane rendering, characterized before GuideMode was split up
 * (complexity refactor). Pins what the other Study suites leave loose: the
 * empty/selection hints, the step-number colors, the exam picker's
 * placeholder, the rendered guide (chips, overview, topics, concepts), the
 * Regenerate button's label/disabled states, and the Recent guides rail
 * (active entry styling, fallbacks, the 20-entry cap, hidden on mobile).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// The page reads ?course= / ?exam= at mount; per-test control without remocking.
const search = { qs: "" };
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search.qs),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

const mobile = { value: false };
vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => mobile.value,
}));

vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: () => null,
}));

// The real renderer drags in mermaid/katex; the guide pane only hands it text.
vi.mock("@/components/chat/MarkdownChat", () => ({
  MarkdownChat: ({ children }: { children: string }) => <span data-md="">{children}</span>,
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getStudyGuideExams: vi.fn(async () => ({ exams: [] })),
  getStudyGuide: vi.fn(),
  regenerateStudyGuide: vi.fn(),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
}));

// The guide pane is a page of its own now; these suites keep their old name for it.
import { StudyGuide as Study } from "./StudyGuide";
import { ToastProvider } from "../ToastProvider";
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

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function course(id: string, code: string, name: string): EnrolledCourse {
  return {
    enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name,
    school: "BU", department: "CS", color: null, nickname: null, node_count: 0,
    enrolled_at: "2025-09-01", term: "Fall 2025",
  };
}

function entry(id: string, examId: string, title: string, courseId = "c1") {
  return {
    id, course_id: courseId, exam_id: examId, course_name: "Intro to CS",
    exam_title: title, overview: "", generated_at: "2026-04-01T00:00:00Z",
  };
}

const FULL_GUIDE = {
  exam: "Midterm 1",
  due_date: "2026-05-01",
  overview: "Overview text",
  topics: [
    { name: "Recursion", importance: "Shows up every year", concepts: ["Base case", "Call stack"] },
    { name: "Sorting", importance: "", concepts: [] },
  ],
};

const GENERATED_AT = "2026-04-01T12:00:00Z";

function renderStudy() {
  return render(
    <ToastProvider>
      <Study />
    </ToastProvider>,
  );
}

function selectTriggers() {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>('button[aria-haspopup="listbox"]'),
  );
}
const courseTrigger = () => selectTriggers()[0];
const examTrigger = () => selectTriggers()[1];

/** The "01"/"02" step markers above the two pickers. */
const stepColor = (n: "01" | "02") => screen.getByText(n).style.color;

async function pickCourse(code = "CS101") {
  await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));
  await userEvent.click(await screen.findByRole("option", { name: new RegExp(code) }));
}

beforeEach(() => {
  search.qs = "";
  mobile.value = false;
  mockedCourses.mockResolvedValue({ courses: [course("c1", "CS101", "Intro to CS")] });
  mockedCached.mockResolvedValue({ guides: [] });
  mockedExams.mockResolvedValue({ exams: [] });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Study guide pane — before anything is picked", () => {
  it("invites a course pick and keeps the exam picker locked", async () => {
    renderStudy();

    expect(await screen.findByText("Pick a course to get started")).toBeTruthy();
    expect(screen.getByText(/Your generated study guides live here/)).toBeTruthy();
    expect(examTrigger()).toBeDisabled();
    expect(examTrigger()).toHaveTextContent("Select a course first");
    expect(stepColor("01")).toBe("var(--text-muted)");
    expect(stepColor("02")).toBe("var(--text-muted)");
    expect(screen.queryByRole("button", { name: /regenerate/i })).toBeNull();
  });

  it("shows the empty rail copy when there are no generated guides", async () => {
    renderStudy();

    expect(await screen.findByText("Recent guides")).toBeTruthy();
    expect(await screen.findByText("No generated guides yet.")).toBeTruthy();
  });

  it("lists course code with the course name as its description", async () => {
    renderStudy();
    await userEvent.click(await screen.findByRole("button", { name: /pick a course/i }));

    const option = await screen.findByRole("option", { name: /CS101/ });
    expect(option).toHaveTextContent("Intro to CS");
  });
});

describe("Study guide pane — a course is picked", () => {
  it("says there are no exams yet when the course has none", async () => {
    renderStudy();
    await pickCourse();

    expect(await screen.findByText("No exams for this course yet")).toBeTruthy();
    expect(screen.queryByText("Choose an exam")).toBeNull();
    expect(screen.queryByText("Pick a course to get started")).toBeNull();
    expect(stepColor("01")).toBe("var(--accent)");
    expect(stepColor("02")).toBe("var(--text-dim)");
    expect(examTrigger()).toBeEnabled();
    expect(examTrigger()).toHaveTextContent("Pick an exam…");
  });

  it("shows Loading… and locks the exam picker while the exams load", async () => {
    const exams = deferred<{ exams: { id: string; title: string; due_date: string }[] }>();
    mockedExams.mockReturnValue(exams.promise);
    renderStudy();
    await pickCourse();

    await waitFor(() => expect(examTrigger()).toHaveTextContent("Loading…"));
    expect(examTrigger()).toBeDisabled();
    // Neither hint while the list is still coming.
    expect(screen.queryByText("No exams for this course yet")).toBeNull();
    expect(screen.queryByText("Choose an exam")).toBeNull();

    exams.resolve({ exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-05-01" }] });
    expect(await screen.findByText("Choose an exam")).toBeTruthy();
  });

  it("asks for an exam once the course has some, with due dates in the options", async () => {
    mockedExams.mockResolvedValue({
      exams: [
        { id: "e1", title: "Midterm 1", due_date: "2026-05-01" },
        { id: "e2", title: "Final", due_date: "" },
      ],
    });
    renderStudy();
    await pickCourse();

    expect(await screen.findByText("Choose an exam")).toBeTruthy();
    expect(screen.getByText(/generated from your course material the first time/)).toBeTruthy();
    expect(screen.queryByText("No exams for this course yet")).toBeNull();

    await userEvent.click(examTrigger());
    expect(await screen.findByRole("option", { name: /Midterm 1/ })).toHaveTextContent("Due 2026-05-01");
    expect(screen.getByRole("option", { name: /Final/ })).not.toHaveTextContent("Due");
  });
});

describe("Study guide pane — a loaded guide", () => {
  beforeEach(() => {
    mockedCached.mockResolvedValue({ guides: [entry("g1", "e1", "Midterm 1")] });
  });

  it("renders the header chips, overview, topics and concepts", async () => {
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    expect(await screen.findByText("Overview text")).toBeTruthy();
    expect(screen.getByText("Due 2026-05-01")).toBeTruthy();
    const stamp = screen.getByText(/^Cached · /);
    expect(stamp).toHaveTextContent(`Cached · ${new Date(GENERATED_AT).toLocaleString()}`);
    expect(screen.getByText("Topic 1")).toBeTruthy();
    expect(screen.getByText("Topic 2")).toBeTruthy();
    expect(screen.getByText("Recursion")).toBeTruthy();
    expect(screen.getByText("Shows up every year")).toBeTruthy();
    const items = screen.getAllByRole("listitem").map(li => li.textContent);
    expect(items).toEqual(["Base case", "Call stack"]);
    // The concept-less topic renders no list at all.
    expect(screen.getAllByRole("list")).toHaveLength(1);
    // Overview + importance + 2 concepts go through the markdown renderer.
    expect(document.querySelectorAll("[data-md]")).toHaveLength(4);
    expect(screen.getByRole("button", { name: /^Regenerate$/ })).toBeEnabled();
  });

  it("labels a freshly built guide Fresh, and omits an absent due date / overview", async () => {
    mockedGuide.mockResolvedValue({
      guide: { exam: "Midterm 1", due_date: "", overview: "", topics: [] },
      generated_at: "",
      cached: false,
    });
    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    const stamp = await screen.findByText(/^Fresh ·/);
    expect(stamp.textContent).toBe("Fresh · ");
    expect(screen.queryByText(/^Due /)).toBeNull();
    expect(document.querySelectorAll("[data-md]")).toHaveLength(0);
  });

  it("shows Regenerating…, the skeleton AND the old guide while it rebuilds", async () => {
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    const regen = deferred<Awaited<ReturnType<typeof regenerateStudyGuide>>>();
    mockedRegenerate.mockReturnValue(regen.promise);
    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));
    await userEvent.click(await screen.findByRole("button", { name: /^Regenerate$/ }));

    const busy = await screen.findByRole("button", { name: /Regenerating…/ });
    expect(busy).toBeDisabled();
    expect(screen.getByText("Overview text")).toBeTruthy();
    expect(document.querySelector('[style*="max-width: 880px"]')).not.toBeNull();

    regen.resolve({
      success: true,
      guide: { ...FULL_GUIDE, overview: "Rebuilt overview" },
      generated_at: GENERATED_AT,
    });
    expect(await screen.findByText("Rebuilt overview")).toBeTruthy();
    expect(await screen.findByText("Study guide regenerated.")).toBeTruthy();
    expect(screen.getByText(/^Fresh ·/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Regenerate$/ })).toBeEnabled();
    expect(document.querySelector('[style*="max-width: 880px"]')).toBeNull();
  });

  it("toasts a failed regenerate and keeps the old guide", async () => {
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    mockedRegenerate.mockRejectedValue(new Error('{"detail":"Regeneration broke."}'));
    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));
    await userEvent.click(await screen.findByRole("button", { name: /^Regenerate$/ }));

    const toasts = await screen.findAllByRole("status");
    expect(toasts.map(t => t.textContent).join(" ")).toContain("Regeneration broke.");
    expect(screen.getByText("Overview text")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Regenerate$/ })).toBeEnabled();
  });

  it("shows only the skeleton while a guide is loading", async () => {
    const load = deferred<Awaited<ReturnType<typeof getStudyGuide>>>();
    mockedGuide.mockReturnValue(load.promise);
    renderStudy();
    await userEvent.click(await screen.findByText("Midterm 1"));

    await waitFor(() =>
      expect(document.querySelector('[style*="max-width: 880px"]')).not.toBeNull(),
    );
    expect(screen.queryByText("Choose an exam")).toBeNull();

    load.resolve({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    expect(await screen.findByText("Overview text")).toBeTruthy();
    expect(document.querySelector('[style*="max-width: 880px"]')).toBeNull();
  });
});

describe("Study guide pane — Recent guides rail", () => {
  it("highlights the open entry only, and falls back for untitled exams", async () => {
    mockedCached.mockResolvedValue({
      guides: [entry("g1", "e1", "Midterm 1"), { ...entry("g2", "e2", ""), exam_title: "" }],
    });
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    renderStudy();

    const aside = (await screen.findByText("Recent guides")).closest("aside")!;
    const untitled = await within(aside).findByText("Untitled exam");
    const rows = within(aside).getAllByRole("button");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.style.background).toBe("transparent");
      expect(row.style.border).toBe("1px solid transparent");
    }
    const date = new Date("2026-04-01T00:00:00Z").toLocaleDateString();
    expect(rows[0]).toHaveTextContent(`Intro to CS · ${date}`);

    await userEvent.click(within(aside).getByText("Midterm 1"));
    await screen.findByText("Overview text");

    expect(rows[0].style.background).toBe("var(--bg-panel)");
    expect(rows[0].style.border).toBe("1px solid var(--border)");
    expect(untitled.closest("button")!.style.background).toBe("transparent");
  });

  it("shows at most 20 entries", async () => {
    mockedCached.mockResolvedValue({
      guides: Array.from({ length: 25 }, (_, i) => entry(`g${i}`, `e${i}`, `Exam ${i}`)),
    });
    renderStudy();

    const aside = (await screen.findByText("Recent guides")).closest("aside")!;
    await within(aside).findByText("Exam 0");
    expect(within(aside).getAllByRole("button")).toHaveLength(20);
    expect(within(aside).queryByText("Exam 20")).toBeNull();
  });

  it("is not rendered on mobile", async () => {
    mobile.value = true;
    mockedCached.mockResolvedValue({ guides: [entry("g1", "e1", "Midterm 1")] });
    renderStudy();

    expect(await screen.findByText("Pick a course to get started")).toBeTruthy();
    await waitFor(() => expect(mockedCached).toHaveBeenCalled());
    expect(screen.queryByText("Recent guides")).toBeNull();
    expect(screen.queryByText("Midterm 1")).toBeNull();
  });
});

describe("Study guide pane — course re-pick and picker wiring", () => {
  it("picking an exam from the picker loads that guide", async () => {
    mockedExams.mockResolvedValue({ exams: [{ id: "e1", title: "Midterm 1", due_date: "" }] });
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    renderStudy();
    await pickCourse();
    await userEvent.click(examTrigger());
    await userEvent.click(await screen.findByRole("option", { name: /Midterm 1/ }));

    expect(await screen.findByText("Overview text")).toBeTruthy();
    expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", undefined);
    expect(stepColor("02")).toBe("var(--accent)");
    expect(courseTrigger()).toHaveTextContent("CS101");
  });
});

describe("Study Guide page — opened from the Study hub", () => {
  it("opens on the hub's course and exam, and links back to that course", async () => {
    search.qs = "course=c1&exam=e1";
    mockedExams.mockResolvedValue({ exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-05-01" }] });
    mockedGuide.mockResolvedValue({ guide: FULL_GUIDE, generated_at: GENERATED_AT, cached: true });
    renderStudy();
    await screen.findByText("Overview text");
    expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", undefined);
    await waitFor(() => expect(courseTrigger().textContent).toContain("CS101"));
    expect(examTrigger().textContent).toContain("Midterm 1");
    expect(screen.getByRole("link", { name: "Back to Study" }).getAttribute("href")).toBe("/study?course=c1");
  });

  it("ignores an exam the course has no guide for (a hub quiz tab) instead of 404ing", async () => {
    search.qs = "course=c1&exam=quiz-3";
    mockedExams.mockResolvedValue({ exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-05-01" }] });
    renderStudy();
    await waitFor(() => expect(examTrigger().disabled).toBe(false));
    expect(mockedExams).toHaveBeenCalledWith("u1", "c1", undefined);
    expect(mockedGuide).not.toHaveBeenCalled();
    expect(screen.queryByText(/exam not found|no longer exists/i)).toBeNull();
  });

  it("falls back to the pickers, quietly, when the hub's exam has no guide in this term", async () => {
    search.qs = "course=c1&exam=e1";
    mockedExams.mockResolvedValue({ exams: [{ id: "e1", title: "Midterm 1", due_date: "2026-05-01" }] });
    mockedGuide.mockRejectedValue(new Error("HTTP 404: Exam not found. It may have been deleted — pick another exam."));
    renderStudy();
    await waitFor(() => expect(mockedGuide).toHaveBeenCalledWith("u1", "c1", "e1", undefined));
    // The course stays, the exam is dropped, and there is no "isn't around" card.
    await waitFor(() => expect(examTrigger().textContent).not.toContain("Midterm 1"));
    expect(courseTrigger().textContent).toContain("CS101");
    expect(screen.queryByText(/isn.t around anymore/i)).toBeNull();
    // Picking that exam by hand still gets the honest answer.
    await userEvent.click(examTrigger());
    await userEvent.click(await screen.findByRole("option", { name: /Midterm 1/ }));
    expect(await screen.findByText(/isn.t around anymore/i)).toBeTruthy();
  });

  it("with nothing in the URL it starts on empty pickers and backs out to the plain hub", async () => {
    renderStudy();
    await screen.findByRole("button", { name: /pick a course/i });
    expect(mockedExams).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Back to Study" }).getAttribute("href")).toBe("/study");
  });
});
