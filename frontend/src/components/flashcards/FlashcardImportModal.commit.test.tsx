// @vitest-environment jsdom
/**
 * Characterization tests for FlashcardImportModal's form + commit path,
 * pinned before the complexity split: course/topic defaults and the late
 * course fill, the course options, the source picker's active state, the
 * reverse-card doubling, the commit button's label/disabled state, and the
 * commit flow (payload, success/error toasts, onImported/onClose ordering,
 * busy state).
 *
 * Plus the two-column layout's own structure: the header and where focus
 * lands, the Paste options row, the right column (course + topic fields,
 * count wording, empty state, flagged rows, row edit / delete, AI clean-up)
 * and the footer's summary line.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act, within } from "@testing-library/react";
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
import Dialog from "../Dialog";

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

const topicInput = () => screen.getByPlaceholderText("e.g. Recursion") as HTMLInputElement;
const pasteTextarea = () => screen.getByPlaceholderText(/paste your cards here/i);
const commitButton = () =>
  screen.getByRole("button", { name: /^(Import \d+ cards?|Importing…)$/ }) as HTMLButtonElement;
// The course field's button. Asserted by ACCESSIBLE NAME, never text content:
// the shared CoursePicker keeps every course's row in the button (hidden) so
// its width never changes, and only the chosen row is exposed.
const courseTrigger = () => within(screen.getByRole("group", { name: "Course" })).getByRole("button");

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.clearAllMocks();
  user.userId = "u1";
});

describe("FlashcardImportModal form (characterization)", () => {
  it("prefills course from the first course and topic from defaultTopic", () => {
    render(modal({ defaultTopic: "Cells" }));
    expect(courseTrigger()).toHaveAccessibleName(/^CS101\s*Intro$/);
    expect(topicInput().value).toBe("Cells");
  });

  it("defaultCourseId wins over the first course; a code-less course shows its name", () => {
    render(modal({ courses: [COURSE, COURSE2], defaultCourseId: "c-2" }));
    expect(courseTrigger()).toHaveAccessibleName("Biology");
  });

  it("lists course options with code and name, the chosen one selected, and picks one", () => {
    render(modal({ courses: [COURSE, COURSE2] }));
    fireEvent.click(courseTrigger());
    const opts = screen.getAllByRole("option");
    expect(opts).toHaveLength(2);
    expect(opts[0]).toHaveTextContent(/^CS101\s*Intro$/);
    expect(opts[1]).toHaveTextContent(/^Biology$/);
    expect(opts.map(o => o.getAttribute("aria-selected"))).toEqual(["true", "false"]);

    fireEvent.click(opts[1]);
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(courseTrigger()).toHaveAccessibleName("Biology");
  });

  it("shows the placeholder with no courses and fills the pick when courses arrive after opening", () => {
    const { rerender } = render(modal({ courses: [] }));
    expect(courseTrigger()).toHaveAccessibleName("Pick a course…");
    rerender(modal({ courses: [COURSE] }));
    expect(courseTrigger()).toHaveAccessibleName(/^CS101/);
  });

  // The picker is a segmented control styled in the CSS module, so the active
  // source is read off `aria-pressed` (what the styling keys on) rather than
  // the inline tab styles this test used to pin.
  it("marks the active source in the picker and moves the mark on click", () => {
    render(modal());
    const picker = screen.getByRole("group", { name: "Import from" });
    const sources = within(picker).getAllByRole("button");
    expect(sources.map(b => b.textContent)).toEqual(["Paste", "Upload", "URL", "AI", "Photo"]);
    const pressed = () => sources.filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.textContent);
    expect(pressed()).toEqual(["Paste"]);

    fireEvent.click(screen.getByRole("button", { name: "URL" }));
    expect(pressed()).toEqual(["URL"]);
    expect(screen.getByRole("button", { name: "Paste" })).toHaveAttribute("aria-pressed", "false");
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

describe("FlashcardImportModal layout", () => {
  const VALID_AND_FLAGGED = "alpha\tbeta\nlonely\ngamma\tdelta";
  const preview = () => screen.getByRole("region", { name: "Cards to import" });

  it("names the dialog by its header title and closes from the header button", () => {
    const onClose = vi.fn();
    render(modal({ onClose }));
    const dialog = screen.getByRole("dialog", { name: "Import flashcards" });
    expect(within(dialog).getByRole("heading", { level: 2, name: "Import flashcards" })).toBeInTheDocument();
    // One close button: Dialog's own is switched off in favour of the header's.
    fireEvent.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("puts focus in the Paste textarea when it opens, with the close button first in the tab order", async () => {
    render(modal());
    // Dialog runs its focus pass on a 20ms timer after opening.
    await act(async () => { await new Promise(r => setTimeout(r, 40)); });
    expect(pasteTextarea()).toHaveFocus();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("button")[0]).toBe(screen.getByRole("button", { name: "Close dialog" }));
  });

  // The modal asks Dialog for min(980px, calc(100vw - 32px)). jsdom's CSSOM
  // drops min(), so the modal's own value cannot be read back here; what can
  // be pinned is the prop it relies on, with a length jsdom keeps.
  it("Dialog's width prop replaces the size preset, and presets are untouched without it", () => {
    const panel = () => screen.getByRole("dialog").firstElementChild as HTMLElement;
    const { rerender } = render(<Dialog open onClose={() => {}} size="xl" width="900px">x</Dialog>);
    expect(panel().style.width).toBe("900px");
    rerender(<Dialog open onClose={() => {}} size="xl">x</Dialog>);
    expect(panel().style.width).toBe("760px");
    rerender(<Dialog open onClose={() => {}}>x</Dialog>);
    expect(panel().style.width).toBe("520px");
  });

  it("does not render at a size preset's width", () => {
    render(modal());
    const panel = screen.getByRole("dialog").firstElementChild as HTMLElement;
    expect(["520px", "640px", "760px"]).not.toContain(panel.style.width);
  });

  it("still closes on Escape", () => {
    const onClose = vi.fn();
    render(modal({ onClose }));
    fireEvent.keyDown(pasteTextarea(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows one quiet line instead of a list while there are no cards", () => {
    render(modal());
    expect(within(preview()).getByText("Cards show up here as you add them.")).toBeInTheDocument();
    expect(within(preview()).getByText("0 cards")).toBeInTheDocument();
    expect(within(preview()).queryByRole("list")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Clean up with AI/ })).toBeDisabled();

    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(screen.queryByText("Cards show up here as you add them.")).not.toBeInTheDocument();
    expect(within(preview()).getAllByRole("listitem")).toHaveLength(1);
  });

  it("counts the cards in plain words and mentions flagged rows only when there are some", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\ngamma\tdelta" } });
    expect(within(preview()).getByText("2 cards")).toBeInTheDocument();
    expect(within(preview()).queryByText(/a look/)).not.toBeInTheDocument();

    fireEvent.change(pasteTextarea(), { target: { value: VALID_AND_FLAGGED } });
    expect(within(preview()).getByText("2 cards")).toBeInTheDocument();
    expect(within(preview()).getByText("1 needs a look")).toBeInTheDocument();

    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\nlonely\nalso lonely" } });
    expect(within(preview()).getByText("1 card")).toBeInTheDocument();
    expect(within(preview()).getByText("2 need a look")).toBeInTheDocument();
  });

  it("lists each card as number, term, definition and a delete button", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\ngamma\tdelta" } });
    const rows = within(preview()).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("2");
    expect(within(rows[1]).getByLabelText("Term, row 2")).toHaveValue("gamma");
    expect(within(rows[1]).getByLabelText("Definition, row 2")).toHaveValue("delta");
    expect(within(rows[1]).getByRole("button", { name: "Delete row 2" })).toBeInTheDocument();
    expect(rows[1]).not.toHaveAttribute("data-flagged");
  });

  it("marks a flagged row with its reason, and filling it in clears the flag", () => {
    render(modal({ defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: VALID_AND_FLAGGED } });
    const flagged = () => within(preview()).getAllByRole("listitem")[1];
    expect(flagged()).toHaveAttribute("data-flagged");
    expect(flagged()).toHaveTextContent("Missing definition");
    expect(commitButton()).toHaveTextContent("Import 2 cards");

    fireEvent.change(screen.getByLabelText("Definition, row 2"), { target: { value: "alone" } });
    expect(flagged()).not.toHaveAttribute("data-flagged");
    expect(flagged()).not.toHaveTextContent("Missing definition");
    expect(within(preview()).getByText("3 cards")).toBeInTheDocument();
    expect(within(preview()).queryByText(/a look/)).not.toBeInTheDocument();
    expect(commitButton()).toHaveTextContent("Import 3 cards");
  });

  it("flags a row the user emptied, with a reason of its own", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    fireEvent.change(screen.getByLabelText("Term, row 1"), { target: { value: "" } });
    const row = within(preview()).getByRole("listitem");
    expect(row).toHaveAttribute("data-flagged");
    expect(row).toHaveTextContent("Term or definition is empty");
    expect(within(preview()).getByText("1 needs a look")).toBeInTheDocument();
  });

  it("deletes a row from the deck", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: VALID_AND_FLAGGED } });
    fireEvent.click(screen.getByRole("button", { name: "Delete row 2" }));
    expect(within(preview()).getAllByRole("listitem")).toHaveLength(2);
    expect(within(preview()).queryByText(/a look/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Term, row 3")).toHaveValue("gamma");
    expect(commitButton()).toHaveTextContent("Import 2 cards");
  });

  it("cleans up the filled-in rows with AI and replaces the deck with the reply", async () => {
    let resolve!: (v: unknown) => void;
    api.importCleanup.mockReturnValue(new Promise(r => { resolve = r; }));
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: VALID_AND_FLAGGED } });
    fireEvent.click(screen.getByRole("button", { name: /Clean up with AI/ }));

    expect(api.importCleanup).toHaveBeenCalledWith("u1", [
      { front: "alpha", back: "beta" },
      { front: "gamma", back: "delta" },
    ]);
    expect(screen.getByRole("button", { name: /Cleaning…/ })).toBeDisabled();

    await act(async () => { resolve({ cards: [{ front: "Alpha", back: "Beta" }] }); });
    expect(toast.success).toHaveBeenCalledWith("Cleaned up.");
    expect(within(preview()).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByLabelText("Term, row 1")).toHaveValue("Alpha");
    expect(screen.getByRole("button", { name: /Clean up with AI/ })).not.toBeDisabled();
  });

  it("reports a failed clean-up and keeps the deck", async () => {
    api.importCleanup.mockRejectedValue(new Error("boom"));
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Clean up with AI/ })); });
    expect(toast.error).toHaveBeenCalledWith("Cleanup failed: Error: boom");
    expect(screen.getByLabelText("Term, row 1")).toHaveValue("alpha");
  });

  it("warns instead of calling the API when no row is filled in", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "lonely" } });
    fireEvent.click(screen.getByRole("button", { name: /Clean up with AI/ }));
    expect(toast.warn).toHaveBeenCalledWith("No valid cards to clean up.");
    expect(api.importCleanup).not.toHaveBeenCalled();
  });

  it("puts the course and topic fields first in the right column, each under its label", () => {
    render(modal({ courses: [COURSE, COURSE2], defaultTopic: "Cells" }));
    // Course: a group named by its label, holding the picker's button, which
    // is named by the course it shows.
    expect(within(preview()).getByRole("group", { name: "Course" })).toContainElement(courseTrigger());
    expect(courseTrigger()).toHaveAttribute("aria-haspopup", "listbox");
    expect(courseTrigger()).toHaveAccessibleName(/^CS101\s*Intro$/);
    // Topic: named by its visible label; the same input the placeholder finds.
    expect(within(preview()).getByRole("textbox", { name: "Topic" })).toBe(topicInput());
    expect(topicInput()).toHaveValue("Cells");
    // Where the cards go comes before what they are.
    const count = within(preview()).getByText("0 cards");
    expect(topicInput().compareDocumentPosition(count) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("falls back to a plain select with a placeholder while the chosen course is not in the list", () => {
    render(modal({ courses: [COURSE, COURSE2], defaultCourseId: "" }));
    expect(courseTrigger()).toHaveAccessibleName("Pick a course…");
    expect(commitButton()).toBeDisabled();
    fireEvent.click(courseTrigger());
    fireEvent.click(screen.getByRole("option", { name: /Biology/ }));
    expect(courseTrigger()).toHaveAccessibleName("Biology");
  });

  it("says in the footer what Import will do, or what it is waiting for", () => {
    render(modal({ courses: [COURSE, COURSE2] }));
    const footer = screen.getByRole("button", { name: "Cancel" }).closest("footer") as HTMLElement;
    expect(footer).toHaveTextContent("Nothing to import yet");
    // The footer holds the summary and the two buttons, nothing else.
    expect(within(footer).getAllByRole("button").map(b => b.textContent)).toEqual(["Cancel", "Import 0 cards"]);
    expect(within(footer).queryByRole("textbox")).not.toBeInTheDocument();

    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta\ngamma\tdelta" } });
    expect(within(footer).getByText("2 cards into CS101 · add a topic to import")).toBeInTheDocument();

    fireEvent.change(topicInput(), { target: { value: "  Recursion " } });
    expect(within(footer).getByText("2 cards into CS101 · Recursion")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(within(footer).getByText("4 cards into CS101 · Recursion")).toBeInTheDocument();

    fireEvent.click(courseTrigger());
    fireEvent.click(screen.getByRole("option", { name: /Biology/ }));
    expect(within(footer).getByText("4 cards into Biology · Recursion")).toBeInTheDocument();
  });

  it("asks for a course in the footer when there is none", () => {
    render(modal({ courses: [], defaultTopic: "Bio" }));
    fireEvent.change(pasteTextarea(), { target: { value: "alpha\tbeta" } });
    expect(screen.getByText("1 card · pick a course to import")).toBeInTheDocument();
  });

  it("orders the regions header, source, course + topic, preview, footer", () => {
    render(modal());
    const inOrder = [
      screen.getByRole("heading", { name: "Import flashcards" }),
      screen.getByRole("region", { name: "Card source" }),
      screen.getByRole("group", { name: "Course" }),
      screen.getByText("Cards show up here as you add them."),
      screen.getByRole("button", { name: "Cancel" }),
    ];
    for (let i = 1; i < inOrder.length; i++) {
      expect(inOrder[i - 1].compareDocumentPosition(inOrder[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(within(screen.getByRole("region", { name: "Card source" })).getByRole("textbox")).toBe(pasteTextarea());
  });
});

describe("FlashcardImportModal Paste options row", () => {
  const source = () => screen.getByRole("region", { name: "Card source" });
  const format = () => screen.getByRole("group", { name: "Card format" });
  const termSeparator = () => screen.getByRole("button", { name: "Between term and definition" });
  const cardSeparator = () => screen.getByRole("button", { name: "Between cards" });
  const pick = (trigger: HTMLElement, option: string) => {
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: option }));
  };

  it("sits under the textarea: the format switch first, then the two separators as one sentence", () => {
    render(modal());
    const after = (a: Node, b: Node) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after(pasteTextarea(), format())).toBe(true);
    expect(after(format(), termSeparator())).toBe(true);
    expect(after(termSeparator(), cardSeparator())).toBe(true);

    expect(within(format()).getAllByRole("button").map(b => [b.textContent, b.getAttribute("aria-pressed")])).toEqual([
      ["Term / Definition", "true"],
      ["Cloze deletion (AI)", "false"],
    ]);
    // Inline words beside each select; the selects keep their own names and
    // show the default separators.
    expect(within(source()).getByText("Split terms by")).toBeInTheDocument();
    expect(within(source()).getByText("and cards by")).toBeInTheDocument();
    expect(termSeparator()).toHaveTextContent("Tab");
    expect(cardSeparator()).toHaveTextContent("New line");
    // The old stacked captions are gone.
    expect(within(source()).queryByText("Between term and definition")).not.toBeInTheDocument();
  });

  it("re-parses with the separators picked, a custom one included", () => {
    render(modal());
    fireEvent.change(pasteTextarea(), { target: { value: "a,b" } });
    expect(commitButton()).toHaveTextContent("Import 0 cards");
    pick(termSeparator(), "Comma");
    expect(commitButton()).toHaveTextContent("Import 1 card");

    expect(screen.queryByPlaceholderText("Custom separator")).not.toBeInTheDocument();
    pick(termSeparator(), "Custom…");
    const custom = screen.getByPlaceholderText("Custom separator");
    expect(custom).toHaveAccessibleName("Custom separator between term and definition");
    expect(commitButton()).toHaveTextContent("Import 0 cards");
    fireEvent.change(pasteTextarea(), { target: { value: "a::b;c::d" } });
    fireEvent.change(custom, { target: { value: "::" } });
    pick(cardSeparator(), "Semicolon");
    expect(commitButton()).toHaveTextContent("Import 2 cards");
  });

  it("words the textarea hint after the separators chosen", () => {
    render(modal());
    expect(pasteTextarea()).toHaveAttribute(
      "placeholder",
      "Paste your cards here. Use Tab between term and definition, Enter between cards.",
    );
    pick(termSeparator(), "Comma");
    pick(cardSeparator(), "Blank line");
    expect(pasteTextarea()).toHaveAttribute(
      "placeholder",
      "Paste your cards here. Use a comma between term and definition, a blank line between cards.",
    );
    pick(termSeparator(), "Custom…");
    expect(pasteTextarea().getAttribute("placeholder")).toContain("Use your separator between term and definition");
    fireEvent.change(screen.getByPlaceholderText("Custom separator"), { target: { value: "::" } });
    expect(pasteTextarea().getAttribute("placeholder")).toContain("Use “::” between term and definition");
  });

  it("swaps the separators for the cloze action in Cloze mode and sends the pasted text", async () => {
    api.importCloze.mockResolvedValue({ cards: [{ front: "The ___ makes ATP", back: "mitochondrion" }] });
    render(modal());
    fireEvent.click(screen.getByRole("button", { name: "Cloze deletion (AI)" }));
    expect(screen.getByRole("button", { name: "Cloze deletion (AI)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Between cards" })).not.toBeInTheDocument();
    const textarea = screen.getByPlaceholderText(/Paste a paragraph/);
    const go = screen.getByRole("button", { name: "Generate cloze cards" });
    expect(go).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "The mitochondrion makes ATP." } });
    await act(async () => { fireEvent.click(go); });
    expect(api.importCloze).toHaveBeenCalledWith("u1", "The mitochondrion makes ATP.");
    expect(toast.success).toHaveBeenCalledWith("Generated 1 cloze cards.");
    expect(commitButton()).toHaveTextContent("Import 1 card");
  });
});
