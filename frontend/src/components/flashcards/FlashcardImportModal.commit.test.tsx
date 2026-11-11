// @vitest-environment jsdom
/**
 * Characterization tests for FlashcardImportModal's form + commit path,
 * pinned before the complexity split: course/topic defaults and the late
 * course fill, the course options, tab button styling, the reverse-card
 * doubling, the commit button's label/disabled state, and the commit flow
 * (payload, success/error toasts, onImported/onClose ordering, busy state).
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";

const api = vi.hoisted(() => ({
  importCommit: vi.fn(),
  importCloze: vi.fn(),
  importCleanup: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

const user = vi.hoisted(() => ({ userId: "u1" as string | null }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: user.userId }),
}));

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
  show: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));

vi.mock("./tabs/UploadTab", () => ({ UploadTab: () => null }));
vi.mock("./tabs/UrlTab", () => ({ UrlTab: () => null }));
vi.mock("./tabs/AiTab", () => ({ AiTab: () => null }));
vi.mock("./tabs/PhotoTab", () => ({ PhotoTab: () => null }));

import { FlashcardImportModal } from "./FlashcardImportModal";

const COURSE: EnrolledCourse = {
  enrollment_id: "e1",
  course_id: "c-1",
  course_code: "CS101",
  course_name: "Intro",
  school: "X",
  department: "CS",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term: "Spring 2026",
};
const COURSE2: EnrolledCourse = { ...COURSE, enrollment_id: "e2", course_id: "c-2", course_code: "", course_name: "Biology" };

interface Opts {
  open?: boolean;
  courses?: EnrolledCourse[];
  defaultCourseId?: string;
  defaultTopic?: string;
  onClose?: () => void;
  onImported?: (n: number) => void;
}

function modal(o: Opts = {}) {
  return (
    <FlashcardImportModal
      open={o.open ?? true}
      onClose={o.onClose ?? (() => {})}
      courses={o.courses ?? [COURSE]}
      defaultCourseId={o.defaultCourseId}
      defaultTopic={o.defaultTopic}
      documents={[]}
      onImported={o.onImported ?? (() => {})}
    />
  );
}

const topicInput = () => screen.getByPlaceholderText("e.g. Cell Biology — Chapter 5") as HTMLInputElement;
const pasteTextarea = () => screen.getByPlaceholderText(/paste your cards here/i);
const commitButton = () =>
  screen.getByRole("button", { name: /^(Import \d+ cards?|Importing…)$/ }) as HTMLButtonElement;
const courseTrigger = () => screen.getByRole("button", { name: /CS101|Biology|Pick a course…/ });

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.clearAllMocks();
  user.userId = "u1";
});

describe("FlashcardImportModal form (characterization)", () => {
  it("prefills course from the first course and topic from defaultTopic", () => {
    render(modal({ defaultTopic: "Cells" }));
    expect(courseTrigger()).toHaveTextContent("CS101");
    expect(topicInput().value).toBe("Cells");
  });

  it("defaultCourseId wins over the first course; a code-less course shows its name", () => {
    render(modal({ courses: [COURSE, COURSE2], defaultCourseId: "c-2" }));
    expect(courseTrigger()).toHaveTextContent("Biology");
  });

  it("lists course options with code as label and name as description", () => {
    render(modal({ courses: [COURSE, COURSE2] }));
    fireEvent.click(courseTrigger());
    const opts = screen.getAllByRole("option");
    expect(opts.map(o => o.textContent)).toEqual(["CS101Intro✓", "Biology"]);
  });

  it("shows the placeholder with no courses and fills the pick when courses arrive after opening", () => {
    const { rerender } = render(modal({ courses: [] }));
    expect(courseTrigger()).toHaveTextContent("Pick a course…");
    rerender(modal({ courses: [COURSE] }));
    expect(courseTrigger()).toHaveTextContent("CS101");
  });

  it("styles the active tab button and the inactive ones", () => {
    render(modal());
    const paste = screen.getByRole("button", { name: "Paste" });
    const url = screen.getByRole("button", { name: "URL" });
    expect(paste.getAttribute("style")).toBe(
      "padding: 8px 14px; font-size: 13px; font-weight: 600; color: var(--accent); background: transparent; border-bottom: 2px solid var(--accent);",
    );
    expect(url.getAttribute("style")).toBe(
      "padding: 8px 14px; font-size: 13px; font-weight: 500; color: var(--text-dim); background: transparent; border-bottom: 2px solid transparent;",
    );
    fireEvent.click(url);
    expect(url.style.fontWeight).toBe("600");
    expect(paste.style.fontWeight).toBe("500");
    expect(screen.getAllByRole("button").map(b => b.textContent)).toEqual(
      expect.arrayContaining(["Paste", "Upload", "URL", "AI", "Photo", "Cancel"]),
    );
  });

  it("disables commit until there are valid cards, a course and a non-blank topic", () => {
    render(modal());
    expect(commitButton()).toHaveTextContent("Import 0 cards");
    expect(commitButton()).toBeDisabled();
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(commitButton()).toHaveTextContent("Import 1 card");
    expect(commitButton()).toBeDisabled();
    fireEvent.change(topicInput(), { target: { value: "   " } });
    expect(commitButton()).toBeDisabled();
    fireEvent.change(topicInput(), { target: { value: "Bio" } });
    expect(commitButton()).not.toBeDisabled();
  });

  it("stays disabled with no course even with cards and a topic", () => {
    render(modal({ courses: [], defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(commitButton()).toHaveTextContent("Import 1 card");
    expect(commitButton()).toBeDisabled();
  });

  it("counts only valid rows and doubles them with reverse cards", () => {
    render(modal({ defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\nlonely\ngamma\tdelta" } });
    expect(commitButton()).toHaveTextContent("Import 2 cards");
    fireEvent.click(screen.getByRole("checkbox"));
    expect(commitButton()).toHaveTextContent("Import 4 cards");
  });
});

describe("FlashcardImportModal commit (characterization)", () => {
  it("commits trimmed topic + reversed cards, toasts with skip note, then onImported before onClose", async () => {
    const calls: string[] = [];
    const onImported = vi.fn(() => calls.push("imported"));
    const onClose = vi.fn(() => calls.push("close"));
    api.importCommit.mockResolvedValue({ inserted: 3, skipped_duplicates: 1 });
    render(modal({ defaultTopic: "  Bio  ", onImported, onClose }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\ngamma\tdelta" } });
    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => { fireEvent.click(commitButton()); });

    expect(api.importCommit).toHaveBeenCalledWith("u1", "c-1", "Bio", [
      { front: "alpha", back: "beta" },
      { front: "beta", back: "alpha" },
      { front: "gamma", back: "delta" },
      { front: "delta", back: "gamma" },
    ], true);
    expect(toast.success).toHaveBeenCalledWith("Imported 3 cards. 1 skipped (duplicates).");
    expect(onImported).toHaveBeenCalledWith(3);
    expect(calls).toEqual(["imported", "close"]);
    expect(toast.warn).not.toHaveBeenCalled();
  });

  it("uses the singular and omits the skip note when nothing was skipped", async () => {
    api.importCommit.mockResolvedValue({ inserted: 1, skipped_duplicates: 0 });
    render(modal({ defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    await act(async () => { fireEvent.click(commitButton()); });
    expect(toast.success).toHaveBeenCalledWith("Imported 1 card.");
  });

  it("shows the busy label while committing and recovers after a failure", async () => {
    let reject!: (e: unknown) => void;
    api.importCommit.mockReturnValue(new Promise((_, r) => { reject = r; }));
    const onClose = vi.fn();
    const onImported = vi.fn();
    render(modal({ defaultTopic: "Bio", onClose, onImported }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    fireEvent.click(commitButton());

    expect(commitButton()).toHaveTextContent("Importing…");
    expect(commitButton()).toBeDisabled();

    await act(async () => { reject(new Error("boom")); });
    expect(toast.error).toHaveBeenCalledWith("Import failed: Error: boom");
    expect(onClose).not.toHaveBeenCalled();
    expect(onImported).not.toHaveBeenCalled();
    expect(commitButton()).toHaveTextContent("Import 1 card");
    expect(commitButton()).not.toBeDisabled();
  });

  it("does nothing without a signed-in user", async () => {
    user.userId = null;
    render(modal({ defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    await act(async () => { fireEvent.click(commitButton()); });
    expect(api.importCommit).not.toHaveBeenCalled();
    expect(toast.warn).not.toHaveBeenCalled();
    expect(commitButton()).toHaveTextContent("Import 1 card");
  });

  it("Cancel calls onClose without committing", () => {
    const onClose = vi.fn();
    render(modal({ onClose }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api.importCommit).not.toHaveBeenCalled();
  });
});
