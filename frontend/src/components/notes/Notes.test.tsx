// @vitest-environment jsdom
/**
 * The Notes page: loading, the title, autosave, Finalize, Regenerate's
 * confirmation, the download menu, and Ask Clov.
 *
 * The editor is an uncontrolled `contentEditable`, so these drive the page
 * through its controls and read the DOM — which is also how a student uses it.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const push = vi.hoisted(() => vi.fn());
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));
// KaTeX is loaded lazily by the math hook and is not what these pin.
vi.mock("@/lib/notes/useNoteMath", () => ({
  useNoteMath: () => ({
    open: vi.fn(), close: vi.fn(), active: null, paletteOpen: false,
    insert: vi.fn(), preview: () => "", refresh: vi.fn(),
    palettePos: { left: 0, top: 0 },
  }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
}));
vi.mock("@/lib/notesApi", () => ({
  getDocumentNotes: vi.fn(),
  saveDocumentNotes: vi.fn(),
  regenerateDocumentNotes: vi.fn(),
  askDocumentNotes: vi.fn(),
}));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import {
  askDocumentNotes, getDocumentNotes, regenerateDocumentNotes, saveDocumentNotes,
} from "@/lib/notesApi";
import { Notes } from "./Notes";
import { ToastProvider } from "../ToastProvider";

const NOTES = {
  document_id: "d1", user_id: "u1",
  title: "Determinants",
  content: "<h2>Overview</h2><p>What a determinant measures.</p>",
  final: false,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "Determinants.pdf",
  category: "lecture_notes" as const, summary: null, concept_notes: null,
  created_at: "2026-11-01T00:00:00Z", processed_at: null,
};

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "MATH210",
  course_name: "Linear Algebra", color: "#C06020",
} as EnrolledCourse;

const renderNotes = () => render(
  <ToastProvider><Notes documentId="d1" /></ToastProvider>,
);

/** The page holds a skeleton for ~1s and autosaves on a 600ms debounce. */
const advance = async (ms: number) => {
  await act(async () => { vi.advanceTimersByTime(ms); });
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
  vi.mocked(getDocumentNotes).mockResolvedValue(NOTES);
  vi.mocked(saveDocumentNotes).mockResolvedValue(NOTES);
  vi.mocked(regenerateDocumentNotes).mockResolvedValue({
    ...NOTES, content: "<h2>Fresh</h2>",
  });
  vi.mocked(askDocumentNotes).mockResolvedValue({ reply: "Row swaps flip the sign." });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Notes: loading", () => {
  it("writes the stored notes into the editor and shows the title", async () => {
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");
    await waitFor(() => expect(editor.innerHTML).toContain("Overview"));
    expect(screen.getByTestId("notes-title").textContent).toBe("Determinants");
    expect(vi.mocked(getDocumentNotes)).toHaveBeenCalledWith("d1", "u1");
  });

  it("names the course it belongs to", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");
    await waitFor(() => expect(screen.getAllByText("MATH210").length).toBeGreaterThan(0));
  });

  it("says so when the notes cannot be opened, and can try again", async () => {
    vi.mocked(getDocumentNotes).mockRejectedValueOnce(new Error("500"));
    renderNotes();
    expect(await screen.findByTestId("notes-load-error")).toBeTruthy();
    expect(screen.queryByTestId("notes-editor")).toBeNull();

    fireEvent.click(screen.getByTestId("notes-load-retry"));
    expect(await screen.findByTestId("notes-editor")).toBeTruthy();
    expect(screen.queryByTestId("notes-load-error")).toBeNull();
  });
});

describe("Notes: autosave", () => {
  it("debounces, and says Saving… until it lands", async () => {
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");

    fireEvent.input(editor);
    expect(screen.getByTestId("notes-save-state").textContent).toContain("Saving");
    // Still inside the debounce: nothing has been sent.
    expect(vi.mocked(saveDocumentNotes)).not.toHaveBeenCalled();

    await advance(700);
    expect(vi.mocked(saveDocumentNotes)).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByTestId("notes-save-state").textContent).toContain("Saved"));
  });

  it("collapses a burst of edits into one save", async () => {
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");
    fireEvent.input(editor);
    await advance(200);
    fireEvent.input(editor);
    await advance(200);
    fireEvent.input(editor);
    await advance(700);
    expect(vi.mocked(saveDocumentNotes)).toHaveBeenCalledTimes(1);
  });

  it("says Not saved rather than claiming success", async () => {
    vi.mocked(saveDocumentNotes).mockRejectedValueOnce(new Error("offline"));
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");
    fireEvent.input(editor);
    await advance(700);
    await waitFor(() =>
      expect(screen.getByTestId("notes-save-state").textContent).toContain("Not saved"));
  });

  it("saves the title as the student types it", async () => {
    renderNotes();
    const title = await screen.findByTestId("notes-title");
    title.textContent = "Determinants, revised";
    fireEvent.input(title);
    await advance(700);
    expect(vi.mocked(saveDocumentNotes).mock.calls[0][2]).toMatchObject({
      title: "Determinants, revised",
    });
  });
});

describe("Notes: finalize", () => {
  it("turns the editor read-only and offers Edit back", async () => {
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");
    expect(editor.getAttribute("contenteditable")).toBe("true");

    fireEvent.click(screen.getByTestId("notes-finalize"));
    await waitFor(() => expect(editor.getAttribute("contenteditable")).toBe("false"));
    expect(screen.getByTestId("notes-finalize").textContent).toContain("Edit");
    // The toolbar is for editing; a finalized document does not need it.
    expect(screen.queryByTestId("notes-toolbar")).toBeNull();

    fireEvent.click(screen.getByTestId("notes-finalize"));
    await waitFor(() => expect(editor.getAttribute("contenteditable")).toBe("true"));
  });

  it("sends the flag", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");
    fireEvent.click(screen.getByTestId("notes-finalize"));
    await advance(700);
    expect(vi.mocked(saveDocumentNotes).mock.calls[0][2]).toMatchObject({ final: true });
  });
});

describe("Notes: regenerate", () => {
  it("asks before replacing the student's work", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");

    fireEvent.click(screen.getByTestId("notes-regenerate"));
    expect(screen.getByTestId("notes-regenerate-confirm")).toBeTruthy();
    expect(vi.mocked(regenerateDocumentNotes)).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("notes-regenerate"));
    await waitFor(() => expect(vi.mocked(regenerateDocumentNotes)).toHaveBeenCalledWith("d1", "u1"));
    const editor = screen.getByTestId("notes-editor");
    await waitFor(() => expect(editor.innerHTML).toContain("Fresh"));
  });
});

describe("Notes: Ask Clov", () => {
  it("sends the question with the notes as context, and shows the reply", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");

    const input = screen.getByTestId("notes-clov-input");
    fireEvent.change(input, { target: { value: "Why does a row swap flip the sign?" } });
    fireEvent.click(screen.getByTestId("notes-clov-send"));

    await waitFor(() => expect(vi.mocked(askDocumentNotes)).toHaveBeenCalled());
    const body = vi.mocked(askDocumentNotes).mock.calls[0][2];
    expect(body.message).toBe("Why does a row swap flip the sign?");
    expect(body).toHaveProperty("notes");

    expect(await screen.findByText("Row swaps flip the sign.")).toBeTruthy();
  });

  it("says so when Clov cannot answer, instead of hanging", async () => {
    vi.mocked(askDocumentNotes).mockRejectedValueOnce(new Error("503"));
    renderNotes();
    await screen.findByTestId("notes-editor");

    fireEvent.change(screen.getByTestId("notes-clov-input"), { target: { value: "Hi" } });
    fireEvent.click(screen.getByTestId("notes-clov-send"));
    expect(await screen.findByText(/couldn't answer that just now/i)).toBeTruthy();
  });

  it("sends nothing for an empty box", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");
    fireEvent.click(screen.getByTestId("notes-clov-send"));
    expect(vi.mocked(askDocumentNotes)).not.toHaveBeenCalled();
  });

  it("closes and reopens, and remembers that it was closed", async () => {
    renderNotes();
    await screen.findByTestId("notes-editor");

    fireEvent.click(screen.getByLabelText("Hide Ask Clov"));
    await waitFor(() => expect(localStorage.getItem("sapling:clovClosed")).toBe("1"));

    fireEvent.click(screen.getByTestId("notes-clov-open"));
    await waitFor(() => expect(localStorage.getItem("sapling:clovClosed")).toBe("0"));
  });
});

describe("Notes: leaving", () => {
  it("flushes a pending save before going back to the Library", async () => {
    renderNotes();
    const editor = await screen.findByTestId("notes-editor");
    fireEvent.input(editor);
    // Still inside the debounce when Back is pressed.
    fireEvent.click(screen.getByTestId("notes-back"));

    await waitFor(() => expect(vi.mocked(saveDocumentNotes)).toHaveBeenCalled());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/library"));
  });
});
