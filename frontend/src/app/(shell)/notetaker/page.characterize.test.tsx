// @vitest-environment jsdom
/**
 * Characterization of the notetaker screen's top-level wiring, pinned before
 * `NotetakerScreen` was split for the complexity budget: the loading and
 * empty states, the four-rail layout (styles + inert per fullscreen
 * mode), Escape handling, the course / concept pickers, tags, the agent
 * actions not already covered by page.stateMachines.test.tsx, the list
 * filters, and that switching notes reuses the editor's DOM (no remount)
 * while the chat rail starts fresh.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import type { EnrolledCourse } from "@/lib/api";
import type { Note as ApiNote, LinkedConcept as ApiLinkedConcept } from "@/lib/types";

const { push, toastError } = vi.hoisted(() => ({ push: vi.fn(), toastError: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

let userState = { userId: "u1" as string | null, userReady: true };
vi.mock("@/context/UserContext", () => ({
  useUser: () => userState,
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
  createNote,
  patchNote,
  summarizeNote,
  extractNoteConcepts,
  linkNoteConcept,
  unlinkNoteConcept,
  getGraph,
} from "@/lib/api";

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
const COURSE_2: EnrolledCourse = {
  ...COURSE,
  enrollment_id: "e-ma",
  course_id: "c2",
  course_code: "MA-123",
  course_name: "Calculus",
  color: "#123456",
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
const NOTE_B: ApiNote = { ...NOTE_A, id: "n2", course_id: "c2", title: "Limits", body: "epsilon delta" };

const LINKED: ApiLinkedConcept = {
  id: "concept-1",
  concept_name: "Recursion",
  mastery_tier: "learning",
  mastery_score: 0.4,
  course_id: "c1",
};

function graphNode(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    concept_name: name,
    mastery_score: 0,
    mastery_tier: "unexplored",
    times_studied: 0,
    last_studied_at: null,
    subject: "CS",
    course_id: "c1",
    ...extra,
  };
}

beforeEach(() => {
  userState = { userId: "u1", userReady: true };
  Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE, COURSE_2] });
  vi.mocked(listNotes).mockResolvedValue({ notes: [NOTE_A, NOTE_B] });
  vi.mocked(listNoteConcepts).mockImplementation(async (noteId: string) => ({
    concepts: noteId === "n1" ? [LINKED] : [],
  }));
  vi.mocked(patchNote).mockResolvedValue({} as ApiNote);
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const titleInput = () => screen.getByPlaceholderText("Untitled note") as HTMLInputElement;
const bodyArea = () =>
  screen.getByPlaceholderText(
    "Start writing — Sapling will pick up concepts as you go.",
  ) as HTMLTextAreaElement;

async function renderPage() {
  const utils = render(<NotetakerPage />);
  await screen.findByPlaceholderText("Untitled note");
  return utils;
}

/** The flex row holding the four rails: list | editor | detail | chat. */
function layout(container: HTMLElement) {
  const row = (container.firstElementChild as HTMLElement).firstElementChild as HTMLElement;
  const [list, editor, detail, chat] = Array.from(row.children) as HTMLElement[];
  return { row, list, editor, detail, chat };
}

describe("loading and empty states", () => {
  it("shows the loading copy until the first load settles", async () => {
    vi.mocked(getCourses).mockReturnValue(new Promise(() => {}));
    const { container } = render(<NotetakerPage />);
    expect(screen.getByText("Loading notes…")).toBeInTheDocument();
    expect((container.firstElementChild as HTMLElement).getAttribute("style")).toBe(
      "display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-muted); font-size: 13px;",
    );
    expect(screen.queryByPlaceholderText("Untitled note")).toBeNull();
  });

  it("shows the loading copy while the user is not ready, without fetching", () => {
    userState = { userId: null, userReady: false };
    render(<NotetakerPage />);
    expect(screen.getByText("Loading notes…")).toBeInTheDocument();
    expect(getCourses).not.toHaveBeenCalled();
  });

  it("with no notes and no courses: disabled create button and the add-a-course hint", async () => {
    vi.mocked(getCourses).mockResolvedValue({ courses: [] });
    vi.mocked(listNotes).mockResolvedValue({ notes: [] });
    render(<NotetakerPage />);
    await screen.findByText("No notes yet");
    expect(screen.getByText("Notetaker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create your first note/ })).toBeDisabled();
    expect(screen.getByText("Add a course first to start taking notes.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("with no notes: the picker opens, Escape closes it, and picking a course creates + opens the note", async () => {
    vi.mocked(listNotes).mockResolvedValue({ notes: [] });
    vi.mocked(createNote).mockResolvedValue({ ...NOTE_A, id: "fresh", title: "Fresh" });
    render(<NotetakerPage />);
    const create = await screen.findByRole("button", { name: /Create your first note/ });
    expect(create).not.toBeDisabled();
    expect(screen.queryByText("Add a course first to start taking notes.")).toBeNull();

    fireEvent.click(create);
    expect(screen.getByText("Which course is this for?")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(create);
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByText("Calculus"));
    await waitFor(() => expect(createNote).toHaveBeenCalledWith("u1", "c2"));
    await waitFor(() => expect(titleInput().value).toBe("Fresh"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the picker's Cancel and backdrop close it; clicks inside the card do not", async () => {
    vi.mocked(listNotes).mockResolvedValue({ notes: [] });
    render(<NotetakerPage />);
    const create = await screen.findByRole("button", { name: /Create your first note/ });
    fireEvent.click(create);
    fireEvent.click(screen.getByText("Which course is this for?"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(create);
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("four-rail layout", () => {
  // jsdom drops `clamp(...)` flex values it cannot parse, and appends style
  // keys in the order React patches them; both are pinned as observed so a
  // changed key order or value shows up here (the clamp() values themselves
  // are invisible to jsdom).
  const NORMAL = {
    row: "flex: 1 1 0%; min-height: 0px; display: flex; gap: 16px; padding: 32px 32px 24px; transition: gap var(--dur-slow) var(--ease), padding var(--dur-slow) var(--ease);",
    list: [
      "min-width: 0px; opacity: 1; overflow: hidden; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease);",
      "false",
    ],
    editor: [
      "flex: 1 1 0%; min-width: 0px; display: flex; justify-content: center;",
      "width: 100%; max-width: none; display: flex; transition: max-width var(--dur-slow) var(--ease);",
    ],
    detail: [
      "min-width: 0px; opacity: 1; overflow: hidden; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease);",
      "false",
    ],
    chat: [
      "flex: 0 0 0px; min-width: 0px; opacity: 0; overflow: hidden; pointer-events: none; display: flex; flex-direction: column; padding-top: 0px; padding-bottom: 0px; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease), padding var(--dur-slow) var(--ease);",
      "true",
    ],
  };
  const FULL = {
    row: "flex: 1 1 0%; min-height: 0px; display: flex; gap: 24px; padding: 24px; transition: gap var(--dur-slow) var(--ease), padding var(--dur-slow) var(--ease);",
    list: [
      "min-width: 0px; opacity: 0; overflow: hidden; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease); flex: 0 0 0px; pointer-events: none;",
      "true",
    ],
    editor: [
      "flex: 1 1 0%; min-width: 0px; display: flex; justify-content: center;",
      "width: 100%; max-width: min(1200px, 96%); display: flex; transition: max-width var(--dur-slow) var(--ease);",
    ],
    detail: [
      "min-width: 0px; opacity: 0; overflow: hidden; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease); flex: 0 0 0px; pointer-events: none;",
      "true",
    ],
    chat: [
      "flex: 0 0 0px; min-width: 0px; opacity: 1; overflow: hidden; display: flex; flex-direction: column; transition: flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease), padding var(--dur-slow) var(--ease); padding-top: 32px; padding-bottom: 32px;",
      "false",
    ],
  };

  it("pins rail styles and inert in normal and fullscreen modes, toggled by the button and Escape", async () => {
    const { container } = await renderPage();
    const snapshot = (l: ReturnType<typeof layout>) => ({
      row: l.row.getAttribute("style"),
      list: [l.list.getAttribute("style"), String(l.list.hasAttribute("inert"))],
      editor: [
        l.editor.getAttribute("style"),
        (l.editor.firstElementChild as HTMLElement).getAttribute("style"),
      ],
      detail: [l.detail.getAttribute("style"), String(l.detail.hasAttribute("inert"))],
      chat: [l.chat.getAttribute("style"), String(l.chat.hasAttribute("inert"))],
    });
    const normal = layout(container);
    expect(snapshot(normal)).toEqual(NORMAL);
    expect(screen.queryByText("Esc to exit")).toBeNull();

    fireEvent.click(screen.getByTitle("Fullscreen editor"));
    const full = layout(container);
    expect(full.row).toBe(normal.row);
    expect(full.list).toBe(normal.list);
    expect(full.chat).toBe(normal.chat);
    expect(snapshot(full)).toEqual(FULL);
    expect(screen.getByText("Esc to exit")).toBeInTheDocument();
    expect(screen.getByTitle("Exit fullscreen (Esc)")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Enter" });
    expect(screen.getByText("Esc to exit")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Esc to exit")).toBeNull();
    const back = snapshot(layout(container));
    expect(back.list[1]).toBe("false");
    expect(back.detail[1]).toBe("false");
    expect(back.chat[1]).toBe("true");
    expect(back.row).toBe(NORMAL.row);

    fireEvent.click(screen.getByTitle("Fullscreen editor"));
    fireEvent.click(screen.getByTitle("Exit fullscreen (Esc)"));
    expect(screen.queryByText("Esc to exit")).toBeNull();
  });

  it("switching notes reuses the editor inputs (no remount) but starts a fresh chat thread", async () => {
    await renderPage();
    const title = titleInput();
    const body = bodyArea();
    const chat = screen.getByPlaceholderText("Ask a quick question…") as HTMLInputElement;
    fireEvent.change(chat, { target: { value: "draft question" } });

    fireEvent.click(screen.getByText("Limits"));
    await waitFor(() => expect(titleInput().value).toBe("Limits"));
    expect(titleInput()).toBe(title);
    expect(bodyArea()).toBe(body);
    expect(bodyArea().value).toBe("epsilon delta");
    const freshChat = screen.getByPlaceholderText("Ask a quick question…") as HTMLInputElement;
    expect(freshChat).not.toBe(chat);
    expect(freshChat.value).toBe("");
  });

  it("the New note button opens the course picker; picking prepends and activates the note", async () => {
    vi.mocked(createNote).mockResolvedValue({ ...NOTE_A, id: "n3", title: "Brand new" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: /New note/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByText("Data Structures"));
    await waitFor(() => expect(titleInput().value).toBe("Brand new"));
    expect(createNote).toHaveBeenCalledWith("u1", "c1");
    expect(screen.queryByRole("dialog")).toBeNull();
    const listTitles = Array.from(document.querySelectorAll("aside.card button div:first-child")).map(
      (d) => d.textContent,
    );
    expect(listTitles.slice(0, 3)).toEqual(["Brand new", "Recursion", "Limits"]);
  });
});

describe("notes list filters", () => {
  it("search matches title / body / course and the course chip filters with a count", async () => {
    await renderPage();
    const search = screen.getByPlaceholderText("Search notes…");
    fireEvent.change(search, { target: { value: "epsilon" } });
    expect(screen.queryByRole("button", { name: /^Recursion/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^Limits/ })).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText("No notes match the current filters.")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "MA-123" }));
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Recursion/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "MA-123" }));
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});

describe("tags", () => {
  it("adds a trimmed tag on Enter, ignores duplicates, removes on click, and autosaves the tags", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    const input = screen.getByPlaceholderText("tag");
    fireEvent.change(input, { target: { value: "  exam " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("button", { name: /^exam/ })).toBeInTheDocument();
    await waitFor(() => expect(patchNote).toHaveBeenCalled(), { timeout: 3000 });
    expect(vi.mocked(patchNote).mock.calls.at(-1)?.[2]).toEqual({ tags: ["exam"] });

    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    const again = screen.getByPlaceholderText("tag");
    fireEvent.change(again, { target: { value: "exam" } });
    fireEvent.keyDown(again, { key: "Enter" });
    expect(screen.getAllByRole("button", { name: /^exam/ })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /^exam/ }));
    expect(screen.queryByRole("button", { name: /^exam/ })).toBeNull();
    expect(screen.getByText("No tags.")).toBeInTheDocument();
    await waitFor(
      () => expect(vi.mocked(patchNote).mock.calls.at(-1)?.[2]).toEqual({ tags: [] }),
      { timeout: 3000 },
    );
  });
});

describe("agent actions", () => {
  it("summarize shows the last summary on success", async () => {
    vi.mocked(summarizeNote).mockResolvedValue({ summary: "A short summary." });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Summarize note" }));
    await screen.findByText("A short summary.");
    expect(screen.getByText("Last summary")).toBeInTheDocument();
    expect(summarizeNote).toHaveBeenCalledWith("n1", "u1");
  });

  it("summarize toasts on failure and clears its busy label", async () => {
    vi.mocked(summarizeNote).mockRejectedValue(new Error("boom"));
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Summarize note" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Summarize note" })).not.toBeDisabled(),
    );
    expect(screen.queryByText("Last summary")).toBeNull();
  });

  it("extract re-reads the linked concepts after the agent call", async () => {
    vi.mocked(extractNoteConcepts).mockResolvedValue({ concepts: ["Base case"], linked: 1 });
    await renderPage();
    await screen.findByText("learning");
    vi.mocked(listNoteConcepts).mockResolvedValue({
      concepts: [LINKED, { ...LINKED, id: "concept-2", concept_name: "Base case", mastery_tier: "mastered" }],
    });
    fireEvent.click(screen.getByRole("button", { name: "Extract concepts" }));
    await screen.findByText("Base case");
    expect(extractNoteConcepts).toHaveBeenCalledWith("n1", "u1");
    expect(screen.getByText("mastered")).toBeInTheDocument();
  });

  it("extract toasts on failure", async () => {
    vi.mocked(extractNoteConcepts).mockRejectedValue(new Error("boom"));
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Extract concepts" }));
    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(1));
  });
});

describe("linked concepts", () => {
  it("the concept picker lists unlinked course concepts, closes on Escape, and links on pick", async () => {
    vi.mocked(getGraph).mockResolvedValue({
      nodes: [
        graphNode("concept-1", "Recursion"),
        graphNode("concept-9", "Memoization"),
        graphNode("root", "CS", { is_subject_root: true }),
        graphNode("other", "Derivatives", { course_id: "c2" }),
      ],
      edges: [],
      stats: {},
    });
    vi.mocked(linkNoteConcept).mockResolvedValue({ linked: true });
    await renderPage();
    await screen.findByText("learning");

    fireEvent.click(screen.getByRole("button", { name: /Link concept/ }));
    let dialog = screen.getByRole("dialog");
    await within(dialog).findByText("Memoization");
    expect(within(dialog).queryByText("Recursion")).toBeNull();
    expect(within(dialog).queryByText("Derivatives")).toBeNull();
    expect(within(dialog).queryByText("CS")).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Link concept/ }));
    dialog = screen.getByRole("dialog");
    fireEvent.click(await within(dialog).findByText("Memoization"));
    await waitFor(() => expect(linkNoteConcept).toHaveBeenCalledWith("n1", "u1", "concept-9"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("unlinks a concept and re-reads the list", async () => {
    vi.mocked(unlinkNoteConcept).mockResolvedValue({ unlinked: true });
    await renderPage();
    const unlink = await screen.findByRole("button", { name: "Unlink Recursion" });
    vi.mocked(listNoteConcepts).mockResolvedValue({ concepts: [] });
    fireEvent.click(unlink);
    await waitFor(() => expect(unlinkNoteConcept).toHaveBeenCalledWith("n1", "u1", "concept-1"));
    await screen.findByText("No concepts linked yet. Sapling will surface them as you write.");
  });
});
